"""Tests for the tracked Markdown inventory generator."""

from pathlib import Path
from unittest.mock import patch

from scripts.generate_markdown_inventory import (
    InventoryRow,
    _content_disposition,
    _linked_markdown_targets,
    default_disposition,
    render_markdown,
    tracked_markdown_files,
)


def test_tracked_markdown_files_excludes_generated_inventory() -> None:
    """The generated inventory must not recursively inventory itself."""
    with patch(
        "scripts.generate_markdown_inventory._git",
        return_value="docs/MARKDOWN_INVENTORY.md\nREADME.md\ndocs/API.md",
    ):
        assert tracked_markdown_files() == ["README.md", "docs/API.md"]


def test_docs_workflow_keeps_inventory_artifact_only() -> None:
    """Documentation CI must not recreate a shared tracked inventory bottleneck."""
    workflow = Path(".github/workflows/docs.yml").read_text(encoding="utf-8")

    assert '--output "${RUNNER_TEMP}/MARKDOWN_INVENTORY.md"' in workflow
    assert "path: ${{ runner.temp }}/MARKDOWN_INVENTORY.md" in workflow
    assert "git status --porcelain -- docs/MARKDOWN_INVENTORY.md" not in workflow
    assert not Path("docs/MARKDOWN_INVENTORY.md").exists()


def test_default_disposition_preserves_code_coupled_docs() -> None:
    """Automation-critical documentation should remain versioned with code."""
    _, _, agents_action, _ = default_disposition("AGENTS.md")
    _, _, prompt_action, _ = default_disposition("prompts/agent-next-task.md")
    _, _, changelog_action, _ = default_disposition("docs/changelog.md")
    _, _, skill_action, _ = default_disposition(".agents/skills/example/SKILL.md")

    assert agents_action == "keep"
    assert prompt_action == "keep"
    assert changelog_action == "historical — preserve"
    assert skill_action == "keep"


def test_docs_hub_contracts_are_kept_with_code() -> None:
    """Docs named by the authoritative hub must not be moved to the Wiki."""
    paths = (
        "docs/API.md",
        "docs/CBL_SERIES_NAMING.md",
        "docs/COMICVINE_RUNTIME_FALLBACK.md",
        "docs/DATABASE_SAVE_LOAD.md",
        "docs/FRONTEND_VISUAL_GRAMMAR.md",
        "docs/GIT_HOOKS.md",
        "docs/ISSUE_EXECUTION_PROTOCOL.md",
        "docs/READING_LIST_EXECUTION_ADR.md",
        "docs/REACT_ARCHITECTURE.md",
        "docs/VERCEL_ARCHITECTURE.md",
        "docs/WIKI_HANDOFF.md",
        "docs/images/README.md",
        "docs/prod-clone-workflow.md",
    )

    for path in paths:
        _, overlap, action, replacement = default_disposition(path)
        assert action == "keep", path
        assert "must change atomically" in overlap
        assert replacement == "—"


def test_issue_plans_are_marked_historical() -> None:
    """Completed issue plans should not silently remain active documentation."""
    _, overlap, action, replacement = default_disposition("docs/issue-plans/123.md")

    assert action == "historical — preserve"
    assert "implementation history" in overlap.casefold()
    assert replacement == "Git history or ComicPile Wiki historical decisions"


def test_legacy_root_docs_receive_explicit_dispositions() -> None:
    """Legacy root Markdown should not be left as an unresolved audit row."""
    _, _, tech_debt_action, tech_debt_replacement = default_disposition("TECH_DEBT.md")
    _, _, rollback_action, rollback_replacement = default_disposition("ROLLBACK.md")

    assert tech_debt_action == "delete"
    assert tech_debt_replacement == "GitHub Issues"
    assert rollback_action == "merge"
    assert "Wiki troubleshooting" in rollback_replacement


def test_unknown_docs_require_content_classification() -> None:
    """Unlinked narrative docs must not be moved to the Wiki automatically."""
    _, _, action, replacement = default_disposition("docs/FEATURE_OVERVIEW.md")

    assert action == "review — classify"
    assert replacement == "Canonical docs hub / ComicPile Wiki"


def test_explicit_historical_marker_overrides_active_default() -> None:
    """Point-in-time records stay historical even when linked from the docs hub."""
    overlap, action, replacement = _content_disposition(
        "docs/EXAMPLE.md",
        "# Example\n\n<!-- docs-path-check: historical -->\n",
        "keep",
    )

    assert action == "historical — preserve"
    assert "provenance" in overlap
    assert "Git history" in replacement


def test_historical_title_or_point_in_time_status_is_classified() -> None:
    """Explicit historical titles/statuses do not depend on one exact marker spelling."""
    for text in (
        "# Historical acceptance checklist\n\n> **Status: point-in-time acceptance record.**\n",
        "# Historical SQL-budget registry\n",
    ):
        _, action, _ = _content_disposition("docs/EXAMPLE.md", text, "keep")
        assert action == "historical — preserve"


def test_marker_mentioned_in_code_is_not_historical() -> None:
    """Inline/fenced examples of the marker must not classify the whole document."""
    text = (
        "# Active guide\n\n"
        "Use `<!-- docs-path-check: historical -->` only for real history.\n\n"
        "```html\n"
        "<!-- docs-path-check: historical -->\n"
        "```\n"
    )
    _, action, _ = _content_disposition("docs/EXAMPLE.md", text, "keep")

    assert action == "keep"


def test_canonical_entry_point_links_are_discovered() -> None:
    """The inventory recognizes active contracts linked from root/docs hubs."""
    linked = _linked_markdown_targets(Path.cwd())

    assert "docs/ARCHITECTURE.md" in linked
    assert "docs/DEPLOYMENT.md" in linked
    assert "docs/READING_LIST_RUNTIME.md" in linked
    assert "docs/README.md" in linked


def test_render_markdown_includes_required_audit_columns_and_escapes_pipes() -> None:
    """The rendered table should match the #879 inventory contract."""
    rendered = render_markdown(
        [
            InventoryRow(
                path="docs/example.md",
                purpose="A | B",
                last_update="2026-08-07",
                overlap="none",
                action="keep",
                replacement="—",
            )
        ]
    )

    assert "Last meaningful update" in rendered
    assert "Duplicate / contradiction evidence" in rendered
    assert "Disposition" in rendered
    assert "Canonical replacement" in rendered
    assert "A \\| B" in rendered
