"""Offline tests for the issue #3887 repository-settings acceptance verifier.

The verifier reads live GitHub state only in its CLI entry point; these tests
exercise the pure evaluation with injectable fakes so they never call an
external service. They cover every acceptance fact, including the owner-only
social-preview upload that cannot be satisfied by a code change.
"""

from __future__ import annotations

import struct
from pathlib import Path

from scripts.check_repo_settings import (
    BASELINE_DESCRIPTION,
    BASELINE_TOPICS,
    OWNER_ACTION,
    PREVIEW_HEIGHT,
    PREVIEW_WIDTH,
    Criterion,
    SocialImage,
    evaluate_repo_state,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def _repo(**overrides: object) -> dict[str, object]:
    """Build fake repository metadata that satisfies every code-observable fact."""
    state: dict[str, object] = {
        "has_discussions": True,
        "description": BASELINE_DESCRIPTION,
        "topics": list(BASELINE_TOPICS),
    }
    state.update(overrides)
    return state


def _image(width: int | None = PREVIEW_WIDTH, height: int | None = PREVIEW_HEIGHT) -> SocialImage:
    """Build a fake ``og:image`` observation with explicit dimensions."""
    return SocialImage(url="https://example.test/social-preview.png", width=width, height=height)


def _by_name(criteria: tuple[Criterion, ...]) -> dict[str, Criterion]:
    """Index evaluated criteria by their stable names."""
    return {criterion.name: criterion for criterion in criteria}


def test_all_acceptance_facts_verify_after_owner_upload() -> None:
    """A live 1280x640 preview plus unchanged settings satisfies every criterion."""
    criteria = evaluate_repo_state(_repo(), _image())

    assert len(criteria) == 4
    assert all(criterion.passed for criterion in criteria)
    assert all(not criterion.owner_action for criterion in criteria)


def test_discussions_must_be_enabled() -> None:
    """Discussions is a repository-admin fact and must be visibly enabled."""
    criteria = _by_name(evaluate_repo_state(_repo(has_discussions=False), _image()))
    discussions = criteria["discussions_enabled"]

    assert not discussions.passed
    assert discussions.owner_action
    assert "has_discussions is not true" in discussions.evidence


def test_social_preview_stays_pending_until_owner_upload() -> None:
    """A 1920x1080 og:image is the unresolved owner-upload criterion."""
    criteria = _by_name(evaluate_repo_state(_repo(), _image(1920, 1080)))
    preview = criteria["social_preview_displayed_at_1280x640"]

    assert not preview.passed
    assert preview.owner_action
    assert "1920x1080" in preview.evidence
    assert "https://example.test/social-preview.png" in preview.evidence
    assert OWNER_ACTION in preview.evidence


def test_missing_social_preview_is_not_treated_as_verified() -> None:
    """An absent og:image cannot satisfy the social-preview criterion."""
    preview = _by_name(evaluate_repo_state(_repo(), None))["social_preview_displayed_at_1280x640"]

    assert not preview.passed
    assert preview.owner_action
    assert "og:image=none" in preview.evidence


def test_non_png_or_unreadable_image_header_does_not_pass() -> None:
    """Unknown dimensions must not accidentally satisfy the size check."""
    preview = _by_name(evaluate_repo_state(_repo(), _image(None, None)))[
        "social_preview_displayed_at_1280x640"
    ]

    assert not preview.passed
    assert "NonexNone" in preview.evidence


def test_topics_must_match_the_frozen_baseline() -> None:
    """The 'unchanged topics' criterion rejects additions and removals."""
    changed = list(BASELINE_TOPICS)
    changed.remove("dice-roller")
    changed.append("new-topic")

    criteria = _by_name(evaluate_repo_state(_repo(topics=changed), _image()))
    topics = criteria["topics_unchanged"]

    assert not topics.passed
    assert "missing=['dice-roller']" in topics.evidence
    assert "extra=['new-topic']" in topics.evidence


def test_description_must_match_the_frozen_baseline() -> None:
    """The 'unchanged description' criterion rejects any edited description."""
    criteria = _by_name(evaluate_repo_state(_repo(description="A new tagline"), _image()))
    description = criteria["description_unchanged"]

    assert not description.passed
    assert "description changed" in description.evidence
    assert "A new tagline" in description.evidence


def test_report_status_tracks_pending_owner_action() -> None:
    """The report must distinguish verified state from pending owner actions."""
    pending_report = render_report(
        "JoshCLWren/comic-pile", evaluate_repo_state(_repo(), _image(1920, 1080))
    )
    complete_report = render_report("JoshCLWren/comic-pile", evaluate_repo_state(_repo(), _image()))

    assert pending_report["verified"] is False
    assert pending_report["pending"] == ["social_preview_displayed_at_1280x640"]
    assert complete_report["verified"] is True
    assert complete_report["pending"] == []
    assert len(complete_report["criteria"]) == 4


def test_verifier_guard_is_invoked_by_ci() -> None:
    """The offline acceptance guard must run in CI, not merely exist locally."""
    workflow = DOCS_WORKFLOW.read_text(encoding="utf-8")
    pytest_steps = [line for line in workflow.splitlines() if "python -m pytest" in line]

    assert any("tests/test_repo_settings_acceptance.py" in line for line in pytest_steps)
    assert workflow.count("tests/test_repo_settings_acceptance.py") >= 2


def test_expected_size_matches_the_committed_social_preview_asset() -> None:
    """The live verifier and the asset guard must agree on the approved size."""
    preview = REPO_ROOT / "docs" / "images" / "social-preview.png"
    with preview.open("rb") as handle:
        header = handle.read(24)

    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", header[16:24]) == (PREVIEW_WIDTH, PREVIEW_HEIGHT)
    assert (PREVIEW_WIDTH, PREVIEW_HEIGHT) == (1280, 640)


def test_verifier_has_no_mutating_github_calls() -> None:
    """The settings verifier must stay read-only even when run manually."""
    source = (REPO_ROOT / "scripts" / "check_repo_settings.py").read_text(encoding="utf-8")

    assert '"gh", "api", f"repos/{repository}"' in source
    assert "--method" not in source
    assert "PATCH" not in source
    assert "POST" not in source
