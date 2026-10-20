"""Regression coverage for historical reader-facing release copy repair."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.release import Release
from comic_pile.release_copy import repair_release_copy, repair_summary


@pytest.mark.parametrize(
    ("stored_title", "expected_title"),
    [
        (
            ": add occasional ComicPile-noticed taste discovery card",
            "Add occasional ComicPile-noticed taste discovery card",
        ),
        (
            ": stop Snooze from permanently demoting thread queue affinity",
            "Stop Snooze from permanently demoting thread queue affinity",
        ),
        (
            "Phase 2: capture the reader timezone on reading sessions",
            "Capture the reader timezone on reading sessions",
        ),
    ],
)
def test_repair_release_copy_removes_dangling_title_separators(
    stored_title: str,
    expected_title: str,
) -> None:
    """Titles left behind by prefix stripping read as complete sentences.

    Args:
        stored_title: Historical stored title with a leading artifact.
        expected_title: Reader-facing title after repair.

    Returns:
        None.
    """
    title, _ = repair_release_copy(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=9101,
        title=stored_title,
        summary="A complete reader-facing summary for this release.",
    )

    assert title == expected_title


@pytest.mark.parametrize(
    ("stored_title", "expected_title"),
    [
        (
            "Fix source_roll_event_id tracking",
            "Fix tracking",
        ),
        (
            "Added `source_roll_event_id` instrumentation detail",
            "Added instrumentation detail",
        ),
        (
            "roll_event rows now expire automatically",
            "Rows now expire automatically",
        ),
    ],
)
def test_repair_release_copy_removes_schema_identifiers_from_titles(
    stored_title: str,
    expected_title: str,
) -> None:
    """Internal schema names must not reach readers through PR-backed titles.

    The frontend used to strip schema identifiers at render time; that cleanup
    now lives in the backend read path, so titles like ``Fix source_roll_event_id
    tracking`` are repaired before publication to the public API.

    Args:
        stored_title: Historical stored title containing a schema identifier.
        expected_title: Reader-facing title after repair.

    Returns:
        None.
    """
    title, _ = repair_release_copy(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=9102,
        title=stored_title,
        summary="A complete reader-facing summary for this release.",
    )

    assert title == expected_title


def test_repair_summary_drops_mid_sentence_hole_and_internal_path() -> None:
    """A summary whose head was stripped and path leaked is omitted whole.

    Args:
        None.

    Returns:
        None.
    """
    repaired = repair_summary(
        "of the recommendation-selection refactor introduces "
        "app/services/recommendation_selection.py, preserving exact "
        "candidate-pool boundaries",
        title="Preserve exact legacy selection",
    )

    assert repaired == ""


def test_repair_summary_keeps_complete_sentences_after_removing_paths() -> None:
    """Artifact-bearing clauses are removed without leaving broken fragments.

    Args:
        None.

    Returns:
        None.
    """
    repaired = repair_summary(
        "A new service in app/services/queue.py keeps your place. "
        "Reopening a comic resumes on the page you left.",
        title="Queue keeps your place",
    )

    assert "app/services" not in repaired
    assert repaired == "Reopening a comic resumes on the page you left."


@pytest.mark.parametrize(
    ("pr_number", "stored_title", "expected_title"),
    [
        (
            1881,
            "time on what’s new",
            "Show relative and absolute timestamps on What's New",
        ),
        (1889, "errors when changing themes", "Theme changes now save your preference"),
        (
            2394,
            "Commit reviewed material into a Reading Plan",
            "Add reviewed material to an existing Reading Plan",
        ),
        (
            2493,
            "Roling should not move the user to anywhere ont he screen",
            "Keep the Roll page at the cover art when reading boundaries load",
        ),
    ],
)
def test_repair_release_copy_restores_curated_historical_titles(
    pr_number: int,
    stored_title: str,
    expected_title: str,
) -> None:
    """Reviewed canonical titles replace malformed stored history.

    Args:
        pr_number: Merged source pull request number.
        stored_title: Historical malformed title.
        expected_title: Verified canonical reader-facing title.

    Returns:
        None.
    """
    title, summary = repair_release_copy(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=pr_number,
        title=stored_title,
        summary="Historical stored summary for this release.",
    )

    assert title == expected_title
    assert summary


def test_repair_release_copy_leaves_pr_less_imports_unchanged() -> None:
    """PR-less imports remain covered by the separate historical backfill.

    Args:
        None.

    Returns:
        None.
    """
    title, summary = repair_release_copy(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=None,
        title=": imported historical entry",
        summary="An imported summary.",
    )

    assert title == ": imported historical entry"
    assert summary == "An imported summary."


@pytest.mark.asyncio
async def test_public_release_read_serves_repaired_copy(
    db: AsyncSession,
    auth_client: AsyncClient,
) -> None:
    """Public list and detail responses apply repair without mutating stored rows.

    Args:
        db: Async test database session shared with the API dependency.
        auth_client: Authenticated async API client.

    Returns:
        None.
    """
    now = datetime.now(UTC)
    dangling = Release(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=9201,
        source_merge_sha=None,
        merged_at=None,
        released_at=now,
        category="What's New",
        title=": add occasional ComicPile-noticed taste discovery card",
        summary="A new service in app/services/queue.py keeps your place.",
        body=None,
        visibility="public",
        status="published",
        sort_order=0,
        provenance_json={},
    )
    curated = Release(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=1881,
        source_merge_sha=None,
        merged_at=None,
        released_at=now - timedelta(minutes=1),
        category="What's New",
        title="time on what’s new",
        summary=(
            "The What's New page now displays relative and absolute timestamps "
            "for each news item, closing . Incl"
        ),
        body=None,
        visibility="public",
        status="published",
        sort_order=0,
        provenance_json={},
    )
    schema_named = Release(
        source_repository="JoshCLWren/comic-pile",
        source_pr_number=9202,
        source_merge_sha=None,
        merged_at=None,
        released_at=now - timedelta(minutes=2),
        category="What's New",
        title="Fix source_roll_event_id tracking",
        summary="Roll history now keeps a stable reference for every dice event.",
        body=None,
        visibility="public",
        status="published",
        sort_order=0,
        provenance_json={},
    )
    db.add_all([dangling, curated, schema_named])
    await db.flush()
    dangling_id = dangling.id
    curated_id = curated.id
    schema_named_id = schema_named.id
    await db.commit()

    listed = await auth_client.get("/api/v1/releases/", params={"limit": 100, "offset": 0})
    assert listed.status_code == 200
    by_id = {item["id"]: item for item in listed.json()["releases"]}
    assert by_id[dangling_id]["title"] == (
        "Add occasional ComicPile-noticed taste discovery card"
    )
    assert "app/services" not in by_id[dangling_id]["summary"]
    assert by_id[curated_id]["title"] == "Show relative and absolute timestamps on What's New"
    assert "closing . Incl" not in by_id[curated_id]["summary"]
    assert by_id[schema_named_id]["title"] == "Fix tracking"
    assert "source_roll_event_id" not in by_id[schema_named_id]["title"]

    fetched = await auth_client.get(f"/api/v1/releases/{schema_named_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Fix tracking"

    fetched = await auth_client.get(f"/api/v1/releases/{dangling_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == (
        "Add occasional ComicPile-noticed taste discovery card"
    )

    await db.refresh(dangling)
    assert dangling.title == ": add occasional ComicPile-noticed taste discovery card"
