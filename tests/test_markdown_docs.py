"""Tests for Markdown documentation validation helpers."""

from pathlib import Path

from scripts.check_markdown_docs import (
    find_broken_local_links,
    find_unapproved_root_markdown,
    iter_markdown_files,
)


def test_find_broken_local_links_accepts_valid_local_and_external_links(tmp_path: Path) -> None:
    """Valid local, anchor, and external links should pass.

    Args:
        tmp_path: Temporary repository root.

    Returns:
        None.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    source = docs / "README.md"
    source.write_text(
        "[local](target.md) [anchor](#section) [web](https://example.com)\n",
        encoding="utf-8",
    )

    assert find_broken_local_links(tmp_path, [source]) == []


def test_find_broken_local_links_reports_missing_and_escaping_targets(tmp_path: Path) -> None:
    """Missing files and repository-escaping paths should fail validation.

    Args:
        tmp_path: Temporary repository root.

    Returns:
        None.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "README.md"
    source.write_text(
        "[missing](missing.md) [escape](../../outside.md)\n",
        encoding="utf-8",
    )

    errors = find_broken_local_links(tmp_path, [source])

    assert "docs/README.md: missing target: missing.md" in errors
    assert "docs/README.md: link escapes repository: ../../outside.md" in errors


def test_iter_markdown_files_ignores_dependency_directories(tmp_path: Path) -> None:
    """Generated dependency trees should not participate in documentation audits.

    Args:
        tmp_path: Temporary repository root.

    Returns:
        None.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    node_modules = tmp_path / "node_modules" / "package"
    node_modules.mkdir(parents=True)
    (node_modules / "README.md").write_text("# Dependency\n", encoding="utf-8")

    assert iter_markdown_files(tmp_path) == [tmp_path / "README.md"]


def test_find_unapproved_root_markdown_flags_documentation_sprawl(tmp_path: Path) -> None:
    """Unexpected root Markdown should require an explicit ownership decision.

    Args:
        tmp_path: Temporary repository root.

    Returns:
        None.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "RANDOM_NOTES.md").write_text("# Notes\n", encoding="utf-8")

    assert find_unapproved_root_markdown(tmp_path) == ["RANDOM_NOTES.md"]
