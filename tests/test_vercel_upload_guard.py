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


def _last_rule(rules: list[tuple[bool, str]], relative_path: str) -> bool:
    """Return whether the last matching rule leaves a path uploaded.

    Args:
        rules: ``(negated, pattern)`` pairs in file order.
        relative_path: Repository-relative POSIX path.

    Returns:
        True when no rule matches, or the last match is a negation.

    """
    uploaded = True
    for negated, pattern in rules:
        if _rule_matches(pattern, relative_path):
            uploaded = negated
    return uploaded


def _is_uploaded(
    relative_path: str,
    rules: list[tuple[bool, str]] | None = None,
) -> bool:
    """Return whether Vercel uploads a repository-relative path.

    Applies the gitignore rule Vercel's uploader follows: a negation cannot
    re-include a file while any parent directory is still excluded, so every
    ancestor is evaluated before the path itself.

    Args:
        relative_path: Repository-relative POSIX path.
        rules: Optional rule set, defaulting to the repository `.vercelignore`.

    Returns:
        False when an excluded ancestor or a winning non-negated rule drops it.

    """
    active = _ignore_rules() if rules is None else rules
    parts = relative_path.split("/")
    for index in range(1, len(parts)):
        if not _last_rule(active, "/".join(parts[:index])):
            return False
    return _last_rule(active, relative_path)


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


def test_the_original_fixture_location_would_be_rejected() -> None:
    """Pin the regression: the pre-#4631 path must be reported as excluded."""
    assert not _is_uploaded("native/roll-service/tests/fixtures/schema/public_schema.sql")


def test_negation_cannot_reinclude_a_file_under_an_excluded_directory() -> None:
    """Mirror the gitignore parent rule the Vercel uploader uses."""
    rules = [(False, "tests/"), (True, "native/app/tests/keep.sql")]
    assert not _is_uploaded("native/app/tests/keep.sql", rules)


def test_negating_the_directory_lets_a_child_be_reincluded() -> None:
    """A negated directory re-opens the tree for selective includes."""
    rules = [
        (False, "tests/"),
        (True, "native/app/tests/"),
        (False, "native/app/tests/*"),
        (True, "native/app/tests/keep.sql"),
    ]
    assert _is_uploaded("native/app/tests/keep.sql", rules)
    assert not _is_uploaded("native/app/tests/other.sql", rules)
