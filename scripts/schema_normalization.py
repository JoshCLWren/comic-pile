#!/usr/bin/env python3
"""Shared pg_dump schema normalization for the canonical Alembic fixture.

This module is the single implementation behind the Rust fixture export
(:mod:`scripts.export_roll_test_schema`) and the production schema-drift
check (:mod:`scripts.compare_production_schema`). Keeping one normalizer
prevents the two gates from quietly diverging on banner stripping, session
``SET`` lines, the ``public`` schema statement, or the ``pg_trgm``
operator-class qualification.

Normalization deliberately removes only what cannot affect object
identity:

* psql meta-commands and version banners that vary by client version;
* ``SET transaction_timeout = 0;`` which a PostgreSQL 16 loader rejects;
* ``CREATE SCHEMA public;`` because ``public`` always exists;
* the ``pg_trgm`` operator-class qualification, which makes a dump emit
  ``public.gin_trgm_ops`` so replay under an empty ``search_path`` matches
  production object layout.

Comparison-time canonicalization additionally drops non-canonical
``CREATE EXTENSION`` statements (only ``pg_trgm`` is Alembic-owned; see
:func:`strip_noncanonical_extensions`) and sorts whole ``;``-terminated
statements so OID creation order between two databases cannot cause a
false positive. Statement text itself is preserved byte-for-byte inside
each block, so an added or dropped column, index, constraint, or changed
function body remains a real diff. Fixture generation never sorts:
sorted blocks are a comparison view only.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# pg_dump emits psql meta-commands and version banners that vary by client
# version or per invocation. Dropping them keeps the fixture diffable and
# loadable through a plain SQL batch (no psql required).
DROPPED_PREFIXES = ("\\restrict", "\\unrestrict")
DROPPED_COMMENT_PREFIXES = (
    "-- Dumped from database version",
    "-- Dumped by pg_dump version",
)
# pg_dump emits settings newer than the oldest server the suite supports
# (PostgreSQL 16, the CI image). Loading them into 16 is a hard error.
DROPPED_SETTINGS = ("SET transaction_timeout = 0;",)
# `public` always exists; restoring the schema statement only breaks loading.
# The fixture is a whole-database dump so extension creation (pg_trgm, created
# by migration c40080000001) travels with the tables that index with it.
DROPPED_STATEMENTS = ("CREATE SCHEMA public;",)
# pg_dump always emits `SET search_path = ''`. Some client versions then leave
# the pg_trgm GIN operator class unqualified. Qualify it so the fixture replays
# against an empty search_path the same way production objects live in public.
_UNQUALIFIED_GIN_TRGM_OPS = re.compile(r"(?<![\w.])gin_trgm_ops\b")

# Extensions owned by the Alembic migration set. Any other extension found in
# a live database dump (a Neon-managed extension, or a production-only
# extension) is dropped for comparison and reported as intentionally ignored;
# its dependent objects, indexes, and functions are never dropped.
CANONICAL_EXTENSIONS = frozenset({"pg_trgm"})

_CREATE_EXTENSION_RE = re.compile(
    r"^\s*CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'"?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)

# Dollar-quote tag: $tag$ where tag is empty or a valid unquoted identifier.
_DOLLAR_TAG_RE = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def qualify_extension_operator_classes(sql: str) -> str:
    """Qualify ``pg_trgm`` operator classes so empty ``search_path`` can replay.

    Production creates ``pg_trgm`` in ``public`` (Alembic ``c40080000001``).
    The dump must name ``public.gin_trgm_ops`` explicitly because pg_dump
    clears ``search_path`` before emitting index DDL. Already-qualified names
    are left unchanged so regeneration stays idempotent across pg_dump versions.

    Args:
        sql: Schema-only SQL, possibly with unqualified ``gin_trgm_ops``.

    Returns:
        The same SQL with every bare ``gin_trgm_ops`` token schema-qualified.
    """
    return _UNQUALIFIED_GIN_TRGM_OPS.sub("public.gin_trgm_ops", sql)


def normalize_schema(raw: str) -> str:
    """Strip psql-only meta-commands and version-dependent banners.

    Args:
        raw: Raw ``pg_dump --schema-only`` output.

    Returns:
        The same SQL without psql-only lines, with the ``pg_trgm``
        operator-class qualification applied, ending in one newline.
    """
    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith(DROPPED_PREFIXES):
            continue
        if stripped.startswith(DROPPED_COMMENT_PREFIXES):
            continue
        if stripped in DROPPED_SETTINGS:
            continue
        if stripped in DROPPED_STATEMENTS:
            continue
        kept.append(line)
    return qualify_extension_operator_classes("\n".join(kept).rstrip("\n") + "\n")


def ignored_extension_names(raw: str) -> list[str]:
    """List extension names that comparison would intentionally ignore.

    Args:
        raw: Raw ``pg_dump --schema-only`` output.

    Returns:
        Sorted names of ``CREATE EXTENSION`` targets outside
        :data:`CANONICAL_EXTENSIONS`, or an empty list when every dumped
        extension is Alembic-owned.
    """
    names: set[str] = set()
    for line in raw.splitlines():
        match = _CREATE_EXTENSION_RE.match(line)
        if match is None:
            continue
        name = match.group("name").lower()
        if name not in CANONICAL_EXTENSIONS:
            names.add(name)
    return sorted(names)


def strip_noncanonical_extensions(sql: str) -> str:
    """Drop ``CREATE EXTENSION`` statements outside the canonical set.

    Only the ``CREATE EXTENSION`` line itself is removed. Objects created
    from the extension stay in the dump, so an extension that backs real
    tables, indexes, or functions cannot mask drift in how they are
    defined.

    Args:
        sql: Normalized schema SQL.

    Returns:
        The same SQL without non-canonical extension creation lines.
    """
    kept: list[str] = []
    for line in sql.splitlines():
        match = _CREATE_EXTENSION_RE.match(line)
        if match is not None and match.group("name").lower() not in CANONICAL_EXTENSIONS:
            continue
        kept.append(line)
    return "\n".join(kept).rstrip("\n") + "\n"


def split_statements(sql: str) -> list[str]:
    """Split SQL into ``;``-terminated statements, respecting quoted regions.

    The scanner ignores semicolons inside ``--`` and ``/* */`` comments,
    single-quoted strings (including ``E'...'`` backslash escapes and
    doubled quotes), double-quoted identifiers (doubled quotes), and
    dollar-quoted function bodies such as ``$$ ...; ... $$``. Each returned
    statement keeps its terminating ``;`` and any comment lines that
    preceded it in the dump, so an object's ``-- Name: ...`` header travels
    with the statement it describes.

    Args:
        sql: SQL text, already normalized.

    Returns:
        Statements in document order.
    """
    statements: list[str] = []
    current: list[str] = []
    index = 0
    end = len(sql)
    # None in NORMAL state; otherwise one of "sq", "dq", "dollar:<tag>",
    # "line-comment", "block-comment".
    state: str | None = None

    while index < end:
        char = sql[index]
        if state is None:  # NORMAL
            if char == "-" and index + 1 < end and sql[index + 1] == "-":
                state = "line-comment"
                current.append(char)
            elif char == "/" and index + 1 < end and sql[index + 1] == "*":
                state = "block-comment"
                current.append(char)
            elif char == "'":
                state = "sq"
                current.append(char)
            elif char == '"':
                state = "dq"
                current.append(char)
            elif char == "$":
                tag = _DOLLAR_TAG_RE.match(sql, index)
                if tag is not None:
                    state = f"dollar:{tag.group()}"
                    current.append(tag.group())
                    index += len(tag.group())
                    continue
                current.append(char)
            elif char == ";":
                current.append(char)
                statement = "".join(current)
                if statement.strip():
                    statements.append(statement)
                current = []
            else:
                current.append(char)
        elif state == "sq":
            current.append(char)
            if char == "\\" and index + 1 < end:
                current.append(sql[index + 1])
                index += 1
            elif char == "'" and index + 1 < end and sql[index + 1] == "'":
                current.append(sql[index + 1])
                index += 1
            elif char == "'":
                state = None
        elif state == "dq":
            current.append(char)
            if char == '"' and index + 1 < end and sql[index + 1] == '"':
                current.append(sql[index + 1])
                index += 1
            elif char == '"':
                state = None
        elif state == "line-comment":
            current.append(char)
            if char == "\n":
                state = None
        elif state == "block-comment":
            current.append(char)
            if char == "*" and index + 1 < end and sql[index + 1] == "/":
                current.append(sql[index + 1])
                index += 1
                state = None
        elif state.startswith("dollar:"):
            tag = state[len("dollar:") :]
            if sql.startswith(tag, index):
                current.append(tag)
                index += len(tag)
                state = None
                continue
            current.append(char)
        index += 1

    tail = "".join(current)
    if tail.strip():
        statements.append(tail)
    return statements


def canonicalize_for_comparison(raw: str) -> list[str]:
    """Reduce raw ``pg_dump`` output to a sorted, comparison-ready block list.

    Args:
        raw: Raw ``pg_dump --schema-only`` output from either the Alembic
            fixture database or a live database.

    Returns:
        Sorted, whitespace-trimmed ``;``-terminated statements. Sorting the
        whole blocks makes OID creation order irrelevant while preserving
        every byte of statement content, so any real column, index,
        constraint, or function change still appears as a differing block.
    """
    normalized = normalize_schema(raw)
    stripped = strip_noncanonical_extensions(normalized)
    blocks = [block.strip() for block in split_statements(stripped)]
    return sorted(block for block in blocks if block)


@dataclass
class SchemaComparison:
    """Result of comparing two canonicalized schema block lists."""

    only_in_left: list[str] = field(default_factory=list)
    only_in_right: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """Whether both sides hold the same multiset of statements."""
        return not self.only_in_left and not self.only_in_right


def compare_schema_blocks(left: list[str], right: list[str]) -> SchemaComparison:
    """Diff two canonicalized block lists as multisets.

    Duplicate statements (for example, the same ``SET`` line emitted
    once per session) stay meaningful: only surplus occurrences on one
    side are reported.

    Args:
        left: Canonicalized blocks for the fixture side.
        right: Canonicalized blocks for the live side.

    Returns:
        A :class:`SchemaComparison` with blocks exclusive to each side.
    """
    left_counter = Counter(left)
    right_counter = Counter(right)
    only_in_left: list[str] = []
    for block in left:
        if left_counter[block] > right_counter[block]:
            only_in_left.append(block)
            left_counter[block] -= 1
    only_in_right: list[str] = []
    for block in right:
        if right_counter[block] > left_counter[block]:
            only_in_right.append(block)
            right_counter[block] -= 1
    return SchemaComparison(only_in_left=only_in_left, only_in_right=only_in_right)
