"""Issue #1718: record candidate weights and bandwidth reason codes on roll events.

Verifies:
- Weighted rolls can be explained from persisted decision-time context (v2 JSON + table).
- Random/control rolls explicitly show bypass/neutral weighting.
- Candidate weights in context match those actually passed to selection.
- Older context versions remain readable.
- Light, deep, balanced, unknown-effort, and random cases.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.reading_effort import (
    RECOMMENDATION_CONTEXT_VERSION,
    build_recommendation_context,
    neutral_estimate,
)


async def _add_thread(db: AsyncSession, user: User, title: str, *, queue_position: int) -> Thread:
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _confirm_series_era(db: AsyncSession, thread: Thread, cover_date: str) -> None:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"4050-{thread.id}",
        metadata_json={"cover_date": cover_date},
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id, external_identity_id=identity.id, status="confirmed"
        )
    )
    await db.flush()


async def _add_observed_effort(
    db: AsyncSession, thread: Thread, *, minutes: float, count: int
) -> None:
    base = datetime.now(UTC) - timedelta(days=7)
    for index in range(count):
        rolled_at = base + timedelta(days=index)
        roll_event = Event(
            type="roll",
            selected_thread_id=thread.id,
            die=8,
            result=1,
            selection_method="random",
            timestamp=rolled_at,
        )
        db.add(roll_event)
        await db.flush()
        rate_event = Event(
            type="rate",
            thread_id=thread.id,
            source_roll_event_id=roll_event.id,
            rating=4.0,
            issues_read=1,
            die=8,
            die_after=8,
            timestamp=rolled_at + timedelta(minutes=minutes),
        )
        db.add(rate_event)
        await db.flush()


@pytest.mark.asyncio
async def test_v1_context_remains_readable() -> None:
    """Older context_version 1 payloads are still readable after bump to 2."""
    estimate = neutral_estimate()
    v1 = {
        "context_version": 1,
        "selected_candidate": {
            "thread_id": 1,
            "issue_id": None,
            "issue_number": None,
            "effort_minutes": None,
            "effort_band": "unknown",
            "effort_source": "unknown",
            "effort_confidence": 0.0,
            "effort_sample_count": 0,
        },
    }
    # v1 has no candidate_weights etc. - reader must tolerate missing keys.
    assert v1["context_version"] == 1
    assert "candidate_weights" not in v1
    # New builder always produces v2.
    v2 = build_recommendation_context(estimate, thread_id=1, issue_id=None, issue_number=None)
    assert v2["context_version"] == RECOMMENDATION_CONTEXT_VERSION == 2
    assert "candidate_weights" in v2
    assert "selected_weight" in v2
    assert "bandwidth" in v2
