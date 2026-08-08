"""Tests for Markdown documentation validation helpers."""

from pathlib import Path

from scripts.check_markdown_docs import (
    find_broken_local_links,
    find_unapproved_root_markdown,
    iter_markdown_files,
)


def test_find_broken_local_links_accepts_valid_local_and_external_links(tmp_path: Path) -> None:
    """Accept valid inline, reference, anchor, and external links.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    source = docs / "README.md"
    source.write_text(
        "[local](target.md) [reference][target] [collapsed][] [shortcut] "
        "[anchor](#section) [web](https://example.com)\n\n"
        "[target]: target.md\n"
        "[collapsed]: target.md\n"
        "[shortcut]: target.md\n",
        encoding="utf-8",
    )

    assert find_broken_local_links(tmp_path, [source]) == []


def test_find_broken_local_links_reports_missing_and_escaping_targets(tmp_path: Path) -> None:
    """Report invalid inline local targets.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
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


def test_find_broken_local_links_reports_invalid_reference_targets(tmp_path: Path) -> None:
    """Report missing and escaping reference-style local targets.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "README.md"
    source.write_text(
        "[missing][missing-ref] [escape][escape-ref]\n\n"
        "[missing-ref]: missing.md\n"
        "[escape-ref]: ../../outside.md\n",
        encoding="utf-8",
    )

    errors = find_broken_local_links(tmp_path, [source])

    assert "docs/README.md: missing target: missing.md" in errors
    assert "docs/README.md: link escapes repository: ../../outside.md" in errors


def test_find_broken_local_links_reports_undefined_explicit_references(tmp_path: Path) -> None:
    """Report undefined full and collapsed references without flagging ordinary bracketed prose.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "README.md"
    source.write_text(
        "[full][missing-ref] [collapsed][] [ordinary prose]\n",
        encoding="utf-8",
    )

    errors = find_broken_local_links(tmp_path, [source])

    assert "docs/README.md: undefined reference: missing-ref" in errors
    assert "docs/README.md: undefined reference: collapsed" in errors
    assert all("ordinary prose" not in error for error in errors)


def test_iter_markdown_files_ignores_dependency_directories(tmp_path: Path) -> None:
    """Exclude generated dependency trees from documentation audits.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    node_modules = tmp_path / "node_modules" / "package"
    node_modules.mkdir(parents=True)
    (node_modules / "README.md").write_text("# Dependency\n", encoding="utf-8")

    assert iter_markdown_files(tmp_path) == [tmp_path / "README.md"]


def test_find_unapproved_root_markdown_flags_documentation_sprawl(tmp_path: Path) -> None:
    """Require an explicit ownership decision for unexpected root Markdown.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "RANDOM_NOTES.md").write_text("# Notes\n", encoding="utf-8")

    assert find_unapproved_root_markdown(tmp_path) == ["RANDOM_NOTES.md"]
