"""Guard files compiled into Vercel functions against upload exclusion.

Vercel builds from the uploaded source, which is filtered by `.vercelignore`,
not from the CI checkout. A Rust module that `include_str!`s a file under an
excluded directory therefore compiles in CI and fails only in the production
deploy with "couldn't read ...: No such file or directory" (#4620, #4617).

This guard resolves every compile-time include in the Rust sources the Vercel
build compiles and fails when the target would not be uploaded.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VERCEL_IGNORE = REPOSITORY_ROOT / ".vercelignore"

# Sources the `@vercel/rust` builds compile: the two `api/*.rs` binaries and the
# library they depend on.
SHIPPED_RUST_ROOTS = (
    REPOSITORY_ROOT / "api",
    REPOSITORY_ROOT / "native" / "roll-service" / "src",
)

INCLUDE_PATTERN = re.compile(r'include_(?:str|bytes)!\("(?P<path>[^"]+)"\)')


def _ignore_rules() -> list[tuple[bool, str]]:
    """Return ``(negated, pattern)`` pairs from `.vercelignore`.

    Returns:
        Rules in file order; later rules override earlier ones.

    """
    rules: list[tuple[bool, str]] = []
    for raw in VERCEL_IGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        rules.append((negated, line[1:] if negated else line))
    return rules


def _rule_matches(pattern: str, relative_path: str) -> bool:
    """Return whether one `.vercelignore` rule matches a repository path.

    Supports the subset the file uses: anchored rules, directory rules, and
    `*`/`**` globs. Matching a directory rule also matches its descendants.

    Args:
        pattern: One rule without its leading `!`.
        relative_path: Repository-relative POSIX path.

    Returns:
        True when the rule applies to the path.

    """
    anchored = pattern.startswith("/")
    pattern = pattern.strip("/")
    if not pattern:
        return False
    translated = pattern.replace("**", "\0")
    translated = re.escape(translated)
    translated = translated.replace(r"\0", ".*")
    translated = translated.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    prefix = "^" if anchored else r"(?:^|/)"
    return re.search(prefix + translated + r"(?:/.*)?$", relative_path) is not None


def _is_uploaded(relative_path: str) -> bool:
    """Return whether Vercel uploads a repository-relative path.

    Args:
        relative_path: Repository-relative POSIX path.

    Returns:
        False when a non-negated `.vercelignore` rule wins.

    """
    uploaded = True
    for negated, pattern in _ignore_rules():
        if _rule_matches(pattern, relative_path):
            uploaded = negated
    return uploaded


def _compile_time_includes() -> list[tuple[Path, str]]:
    """Return every resolved include target and the source that references it.

    Returns:
        Pairs of (source file, repository-relative target path).

    """
    includes: list[tuple[Path, str]] = []
    for root in SHIPPED_RUST_ROOTS:
        for source in sorted(root.rglob("*.rs")):
            text = source.read_text(encoding="utf-8")
            for match in INCLUDE_PATTERN.finditer(text):
                target = (source.parent / match.group("path")).resolve()
                includes.append((source, target.relative_to(REPOSITORY_ROOT).as_posix()))
    return includes


def test_included_files_are_uploaded_to_vercel() -> None:
    """Every compiled-in file must survive `.vercelignore` filtering."""
    includes = _compile_time_includes()
    assert includes, "expected at least one compile-time include to guard"
    excluded = [
        f"{source.relative_to(REPOSITORY_ROOT).as_posix()} -> {target}"
        for source, target in includes
        if not _is_uploaded(target)
    ]
    assert not excluded, (
        "these compile-time includes live under a `.vercelignore` exclusion, so the "
        "Vercel build cannot read them even though CI can: " + ", ".join(excluded)
    )


def test_alembic_schema_fixture_is_not_under_a_test_exclusion() -> None:
    """The baked schema must live outside the ignored `tests/` trees."""
    fixture = REPOSITORY_ROOT / "native" / "roll-service" / "src" / "schema" / "public_schema.sql"
    relative = fixture.relative_to(REPOSITORY_ROOT).as_posix()
    assert fixture.is_file(), f"missing canonical schema fixture at {relative}"
    assert _is_uploaded(relative), (
        f"{relative} is excluded by .vercelignore; the deployed Rust build embeds it"
    )
    assert "tests" not in fixture.relative_to(REPOSITORY_ROOT).parts, (
        "the schema fixture must not live under tests/, which .vercelignore excludes"
    )
