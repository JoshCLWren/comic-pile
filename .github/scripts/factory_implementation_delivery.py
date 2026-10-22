"""Conservative mechanical evidence that a PR changes executable behavior.

This check is intentionally not a correctness proof. The independent exact-head
reviewer still has to verify each linked-issue requirement and its tests.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
SOURCE_SUFFIXES = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".sh", ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
)
TYPE_LINE = re.compile(
    r"(?im)^\s*(?:\*\*)?(?:issue\s+type|deliverable\s+type|"
    r"work\s+type)\s*:(?:\*\*)?\s*(?:\*\*)?"
    r"(docs-only|documentation-only|documentation|investigation|"
    r"planning|prd|acceptance-only|test-only)(?:\*\*)?\s*$"
)
PATCH_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")


def is_implementation_issue(issue_body: str | None) -> bool:
    """Classify using a structured declaration, not arbitrary issue prose.

    Args:
        issue_body: Authoritative linked issue description.

    Returns:
        True by default, or False for an explicitly typed non-code ticket.
    """
    body = issue_body or ""
    match = TYPE_LINE.search(body)
    return match is None


def _is_docs_path(path: str) -> bool:
    """Whether the file can only serve as documentation."""
    normalized = path.lower().strip()
    return normalized.startswith("docs/") or normalized.endswith(DOC_SUFFIXES)


def _is_test_path(path: str) -> bool:
    """Whether a file contains tests rather than deliverable production code."""
    normalized = path.lower()
    name = normalized.rsplit("/", 1)[-1]
    return (
        normalized.startswith(("tests/", "frontend/src/test/", "frontend/src/unit/"))
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def substantive_changed_files(changed_files: Iterable[str]) -> list[str]:
    """Find candidate behavioral source files, excluding docs and tests.

    Args:
        changed_files: Paths reported by the reviewed PR diff.

    Returns:
        Source file paths that could contain the requested implementation.
    """
    return [
        path for path in changed_files
        if path.strip()
        and path.lower().endswith(SOURCE_SUFFIXES)
        and not _is_docs_path(path)
        and not _is_test_path(path)
    ]


@dataclass
class _LexState:
    """Comment/documentation state for one side of a patch hunk."""

    triple: str = ""
    block: bool = False


def _executable_text(line: str, path: str, state: _LexState) -> str:
    """Remove comments and docstrings while preserving behavioral syntax."""
    python = path.lower().endswith(".py")
    result: list[str] = []
    pos = 0
    while pos < len(line):
        if state.triple:
            end = line.find(state.triple, pos)
            if end < 0:
                return "".join(result).strip()
            pos = end + 3
            state.triple = ""
            continue
        if state.block:
            end = line.find("*/", pos)
            if end < 0:
                return "".join(result).strip()
            pos = end + 2
            state.block = False
            continue
        if python:
            if line[pos] == "#":
                break
            if line.startswith(('"""', "'''"), pos):
                delimiter = line[pos:pos + 3]
                before = "".join(result).strip()
                # A standalone literal after def/class/context is documentation.
                # A literal returned or assigned by code remains behavioral.
                code_literal = bool(re.search(r"(?:=|\breturn|\byield)\s*$", before))
                end = line.find(delimiter, pos + 3)
                if code_literal:
                    result.append("LITERAL")
                    pos = len(line) if end < 0 else end + 3
                else:
                    if end < 0:
                        state.triple = delimiter
                        break
                    pos = end + 3
                continue
        else:
            if line.startswith("//", pos):
                break
            if line.startswith("/*", pos):
                state.block = True
                pos += 2
                continue
        result.append(line[pos])
        pos += 1
    code = "".join(result).strip()
    if python and re.fullmatch(r"[rubfRUBF]*(['\"]).*\1", code):
        return ""
    return re.sub(r"\s+", "", code)


def _has_code_delta(patch: str, path: str) -> bool:
    """Inspect only the old and new executable sides of source-file hunks."""
    deleted: list[str] = []
    added: list[str] = []
    old = _LexState()
    new = _LexState()
    in_hunk = False
    for line in patch.splitlines():
        if line.startswith("@@"):
            old = _LexState()
            new = _LexState()
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("diff --git "):
            break
        if line.startswith("\\ No newline"):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            token = _executable_text(line[1:], path, new)
            if token:
                added.append(token)
        elif line.startswith("-") and not line.startswith("---"):
            token = _executable_text(line[1:], path, old)
            if token:
                deleted.append(token)
        elif line.startswith(" "):
            _executable_text(line[1:], path, old)
            _executable_text(line[1:], path, new)
    # Pure formatting/comments must not qualify. Deletions are valid code edits.
    return bool(added or deleted) and added != deleted


def _file_patches(diff_text: str) -> dict[str, str]:
    """Split a unified Git diff into authoritative per-file patches."""
    patches: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in diff_text.splitlines():
        header = PATCH_HEADER.match(line)
        if header:
            if current:
                patches[current] = "\n".join(lines)
            current = header.group(2)
            lines = [line]
        elif current:
            lines.append(line)
    if current:
        patches[current] = "\n".join(lines)
    return patches


def pr_delivers_implementation(
    issue_body: str | None,
    changed_files: Iterable[str],
    diff_text: str | None = None,
) -> tuple[bool, str]:
    """Reject non-delivering implementations without judging feature correctness.

    Args:
        issue_body: Exact linked-issue body.
        changed_files: File paths of the current PR head.
        diff_text: Full unified patch for that same PR head, if available.

    Returns:
        Whether the mechanical behavioral-diff prerequisite is satisfied,
        plus an actionable reason. Missing diff never counts as evidence.
    """
    if not is_implementation_issue(issue_body):
        return True, "explicit non-implementation issue type; documentation allowed"
    candidates = substantive_changed_files(changed_files)
    if not candidates:
        return False, "implementation issue has no changed production source files"
    if diff_text is None:
        return False, "unavailable source diff; cannot verify executable changes"
    patches = _file_patches(diff_text)
    for path in candidates:
        if path in patches and _has_code_delta(patches[path], path):
            return True, "production executable code changed; semantic review required"
    return (
        False,
        "only documentation, comments, docstrings or formatting changed "
        "in production source files; executable delivery is unverified",
    )
