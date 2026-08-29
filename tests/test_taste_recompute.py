"""Async service tests for recompute_user_taste_signals (issue #1745).

These cover the path that reads a reader's confirmed issue metadata from the
database, derives inferred signals, and persists them through the verdict-
preserving repository helper. They exercise the SQL joined in
:func:`app.services.taste_recompute._confirmed_issue_metadata` so a Cartesian
join regression cannot silently multiply evidence.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.taste_signal import TasteSignal
from app.services.taste_recompute import recompute_user_taste_signals


async def _add_confirmed_issue(
    db: AsyncSession,
    *,
    user_id: int,
    rating: float,
    creator_credits: list[dict[str, object]],
    characters: list[dict[str, object]] | None = None,
) -> Thread:
    """Create one rated thread with a single confirmed issue carrying metadata.

    Args:
        db: Async database session.
        user_id: Owning user id.
        rating: The thread's ``last_rating`` (used as the issue's rating).
        creator_credits: Creator credit dicts for the issue metadata.
        characters: Optional character reference dicts.

    Returns:
        The created :class:`~app.models.thread.Thread`.
    """
    thread = Thread(
        title="thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user_id,
        last_rating=rating,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1)
    db.add(issue)
    await db.flush()
    identity = ExternalIdentity(
        provider="ComicVine",
        entity_type="issue",
        external_id=f"issue-{issue.id}",
        external_url="https://example.com/issue",
        metadata_json={
            "creator_credits": creator_credits,
            "characters": characters or [],
        },
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await db.flush()
    return thread


async def test_recompute_creates_inferred_signal_from_confirmed_history(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirmed issues across threads produce one inferred signal per feature."""
    user_id = default_user.id

    # Baseline thread pulls the mean down but carries no confirmed metadata.
    baseline = Thread(
        title="baseline",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user_id,
        last_rating=3.0,
    )
    async_db.add(baseline)
    await async_db.flush()

    for _ in range(2):
        await _add_confirmed_issue(
            async_db,
            user_id=user_id,
            rating=5.0,
            creator_credits=[{"id": 100, "name": "Alan Moore", "role": "writer"}],
            characters=[{"id": 7, "name": "Swamp Thing"}],
        )

    await recompute_user_taste_signals(async_db, user_id)
    await async_db.commit()

    result = await async_db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == user_id,
            TasteSignal.signal_type == "creator",
            TasteSignal.external_key == "creator:writer:100",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.affinity_estimate > 0
    assert row.evidence_count == 2
    assert row.distinct_thread_count == 2
    assert row.user_verdict is None


async def test_recompute_preserves_existing_verdict_through_service(
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An existing explicit verdict survives a service-driven recomputation."""
    user_id = default_user.id

    seeded = TasteSignal(
        user_id=user_id,
        signal_type="creator",
        external_key="creator:writer:100",
        display_name="Alan Moore",
        affinity_estimate=0.1,
        confidence=0.1,
        evidence_count=1,
        distinct_thread_count=1,
        user_verdict="confirmed",
    )
    async_db.add(seeded)
    await async_db.flush()

    baseline = Thread(
        title="baseline",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user_id,
        last_rating=3.0,
    )
    async_db.add(baseline)
    await async_db.flush()

    for _ in range(3):
        await _add_confirmed_issue(
            async_db,
            user_id=user_id,
            rating=5.0,
            creator_credits=[{"id": 100, "name": "Alan Moore", "role": "writer"}],
        )

    await recompute_user_taste_signals(async_db, user_id)
    await async_db.commit()

    result = await async_db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == user_id,
            TasteSignal.signal_type == "creator",
            TasteSignal.external_key == "creator:writer:100",
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.user_verdict == "confirmed"
    assert row.affinity_estimate > 0.1
    assert row.evidence_count == 3
    assert row.distinct_thread_count == 3
