"""Tests for Markdown documentation validation helpers."""

import subprocess
from pathlib import Path

from scripts.check_markdown_docs import (
    find_broken_anchors,
    find_broken_local_links,
    find_unapproved_root_markdown,
    iter_markdown_files,
)

GOOD_FIRST_ISSUES_URL = (
    "https://github.com/JoshCLWren/comic-pile/issues"
    "?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22"
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


def test_find_broken_anchors_accepts_same_and_cross_document_headings(tmp_path: Path) -> None:
    """Accept fragments for headings in the current file and another tracked document.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text(
        "# Title\n\n## Status / amendments (2026-11-18)\n\n## Duplicate\n\n## Duplicate\n",
        encoding="utf-8",
    )
    source = docs / "README.md"
    source.write_text(
        "# Own heading\n\n"
        "[same](#own-heading) [cross](target.md#status--amendments-2026-11-18) "
        "[duplicate](target.md#duplicate-1)\n",
        encoding="utf-8",
    )

    assert find_broken_anchors(tmp_path, [source]) == []


def test_find_broken_anchors_reports_unresolved_fragments(tmp_path: Path) -> None:
    """Report missing heading fragments without weakening the file-link check.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Title\n", encoding="utf-8")
    source = docs / "README.md"
    source.write_text(
        "[same](#missing) [cross](target.md#nope) [reference][ref] "
        "[external](https://example.com/page#fragment)\n\n"
        "[ref]: target.md#absent\n",
        encoding="utf-8",
    )

    errors = find_broken_anchors(tmp_path, [source])

    assert "docs/README.md: broken anchor: #missing" in errors
    assert "docs/README.md: broken anchor: target.md#nope" in errors
    assert "docs/README.md: broken anchor: target.md#absent" in errors
    assert all("external" not in error for error in errors)


def test_find_broken_anchors_ignores_missing_files_and_code_fences(tmp_path: Path) -> None:
    """Leave missing-file errors to the link check and ignore illustrative headings.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    source = tmp_path / "README.md"
    source.write_text(
        "[missing](gone.md#section)\n\n"
        "```markdown\n## Fenced heading\n```\n\n"
        "[fenced](#fenced-heading)\n",
        encoding="utf-8",
    )

    errors = find_broken_anchors(tmp_path, [source])

    assert errors == ["README.md: broken anchor: #fenced-heading"]
    assert (
        "README.md: missing target: gone.md#section"
        in find_broken_local_links(tmp_path, [source])
    )


def test_find_broken_anchors_ignores_links_inside_fenced_code_blocks(tmp_path: Path) -> None:
    """Skip illustrative inline and reference links without weakening real link checks.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    source = docs / "README.md"
    source.write_text(
        "[real](target.md#target) [bad](target.md#bad)\n\n"
        "```markdown\n[example](target.md#nonexistent) [ref][fenced-ref]\n```\n\n"
        "[fenced-ref]: target.md#also-nonexistent\n",
        encoding="utf-8",
    )

    errors = find_broken_anchors(tmp_path, [source])

    assert errors == ["docs/README.md: broken anchor: target.md#bad"]


def test_find_broken_anchors_accepts_setext_and_html_heading_anchors(tmp_path: Path) -> None:
    """Resolve setext headings and explicit id/name attributes on HTML heading elements.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").write_text(
        "Setext Title\n============\n\n"
        "## Hyphen Setext\n----------------\n\n"
        '<h2 id="explicit-html">HTML heading</h2>\n\n'
        '<a name="legacy-anchor"></a>\n',
        encoding="utf-8",
    )
    source = docs / "README.md"
    source.write_text(
        "[setext](target.md#setext-title) [hyphen](target.md#hyphen-setext) "
        '[html](target.md#explicit-html) [legacy](target.md#legacy-anchor)\n',
        encoding="utf-8",
    )

    assert find_broken_anchors(tmp_path, [source]) == []


def test_current_repository_has_no_broken_anchors() -> None:
    """Keep cross-document navigation valid as active documents move and headings change."""
    root = Path(__file__).parents[1]

    assert find_broken_anchors(root, iter_markdown_files(root)) == []


def test_iter_markdown_files_ignores_generated_directories(tmp_path: Path) -> None:
    """Exclude generated dependency and deployment trees from documentation audits.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    node_modules = tmp_path / "node_modules" / "package"
    node_modules.mkdir(parents=True)
    (node_modules / "README.md").write_text("# Dependency\n", encoding="utf-8")
    vercel_output = tmp_path / ".vercel" / "output" / "static"
    vercel_output.mkdir(parents=True)
    (vercel_output / "README.md").write_text("[stale](missing.md)\n", encoding="utf-8")

    assert iter_markdown_files(tmp_path) == [tmp_path / "README.md"]


def test_iter_markdown_files_uses_tracked_scope_in_git_repo(tmp_path: Path) -> None:
    """Keep tracked validation strict while excluding overlays, archives, and missing files."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    docs = tmp_path / "docs"
    docs.mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    (docs / "tracked.md").write_text("# Tracked\n", encoding="utf-8")
    (docs / "overlay.md").write_text("# Overlay\n", encoding="utf-8")
    (archive / "history.md").write_text("# History\n", encoding="utf-8")
    (tmp_path / "RANDOM_NOTES.md").write_text("# Untracked root notes\n", encoding="utf-8")
    (tmp_path / "TRACKED_NOTES.md").write_text("# Tracked root notes\n", encoding="utf-8")
    missing = docs / "missing.md"
    missing.write_text("# Missing\n", encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "README.md",
            "docs/tracked.md",
            "archive/history.md",
            "TRACKED_NOTES.md",
            "docs/missing.md",
        ],
        check=True,
    )
    missing.unlink()

    assert iter_markdown_files(tmp_path) == [
        tmp_path / "README.md",
        tmp_path / "TRACKED_NOTES.md",
        docs / "tracked.md",
    ]
    assert find_unapproved_root_markdown(tmp_path) == ["TRACKED_NOTES.md"]


def test_find_unapproved_root_markdown_flags_documentation_sprawl(tmp_path: Path) -> None:
    """Require an explicit ownership decision for unexpected root Markdown.

    Args:
        tmp_path: Temporary repository root supplied by pytest.
    """
    (tmp_path / "README.md").write_text("# Root\n", encoding="utf-8")
    (tmp_path / "RANDOM_NOTES.md").write_text("# Notes\n", encoding="utf-8")

    assert find_unapproved_root_markdown(tmp_path) == ["RANDOM_NOTES.md"]


def test_contributing_links_good_first_issue_label_filter() -> None:
    """Keep the newcomer pointer on the canonical good-first-issue label query.

    Args:
        None.

    Returns:
        None.
    """
    contributing = (Path(__file__).parents[1] / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "## Good first issues" in contributing
    assert f"[`good first issue`]({GOOD_FIRST_ISSUES_URL})" in contributing
    assert "## Pre-commit hook" in contributing
    assert "## Testing guidelines" in contributing


def test_documentation_workflow_cannot_rewrite_pull_request_heads() -> None:
    """Keep documentation CI read-only so it cannot replace factory PR heads.

    Args:
        None.

    Returns:
        None.
    """
    workflow = (Path(__file__).parents[1] / ".github/workflows/docs.yml").read_text(
        encoding="utf-8"
    )

    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "persist-credentials: false" in workflow
    assert "git push" not in workflow
