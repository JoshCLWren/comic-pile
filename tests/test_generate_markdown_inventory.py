"""Tests for the tracked Markdown inventory generator."""

from scripts.generate_markdown_inventory import (
    InventoryRow,
    default_disposition,
    render_markdown,
)


def test_default_disposition_preserves_code_coupled_docs() -> None:
    """Automation-critical documentation should remain versioned with code."""
    _, _, agents_action, _ = default_disposition("AGENTS.md")
    _, _, prompt_action, _ = default_disposition("prompts/agent-next-task.md")
    _, _, changelog_action, _ = default_disposition("docs/changelog.md")
    _, _, skill_action, _ = default_disposition(".agents/skills/example/SKILL.md")

    assert agents_action == "keep"
    assert prompt_action == "keep"
    assert changelog_action == "keep"
    assert skill_action == "keep"


def test_issue_plans_are_marked_for_archive() -> None:
    """Completed issue plans should not silently remain active documentation."""
    _, overlap, action, replacement = default_disposition("docs/issue-plans/123.md")

    assert action == "archive"
    assert "implementation history" in overlap
    assert replacement == "Git history or ComicPile Wiki historical decisions"


def test_legacy_root_docs_receive_explicit_dispositions() -> None:
    """Legacy root Markdown should not be left as an unresolved audit row."""
    _, _, tech_debt_action, tech_debt_replacement = default_disposition("TECH_DEBT.md")
    _, _, rollback_action, rollback_replacement = default_disposition("ROLLBACK.md")

    assert tech_debt_action == "delete"
    assert tech_debt_replacement == "GitHub Issues"
    assert rollback_action == "merge"
    assert "Wiki troubleshooting" in rollback_replacement


def test_human_facing_docs_receive_wiki_disposition() -> None:
    """Narrative docs must have a final Wiki disposition rather than 'review'."""
    _, _, action, replacement = default_disposition("docs/FEATURE_OVERVIEW.md")

    assert action == "move to Wiki"
    assert replacement == "ComicPile Wiki"


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
