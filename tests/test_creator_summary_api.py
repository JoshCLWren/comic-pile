"""API coverage for the bounded personal creator summary contract (issue #2028).

One authenticated batch endpoint summarizes the current user's library per
canonical creator key computed from confirmed local ComicVine issue metadata
(no ComicVine call). This module covers the acceptance contract: bounded batch
semantics, headline role classification, latest-effective rating semantics,
one-rating-per-issue-per-creator deduplication, explicit coverage completeness,
zero leakage of another user's library state, request validation, and constant
query count regardless of the number of requested keys.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.creator_summary import manual_creator_id

D1 = datetime(2026, 3, 1, tzinfo=UTC)

_identity_serial = 0


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count - read_through,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position <= read_through else "unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    return thread, issues


async def _confirm_identity(
    db: AsyncSession,
    issue: Issue,
    *,
    creators: list[dict[str, object]] | None = None,
    metadata: dict[str, object] | None = None,
    provider: str = "comicvine",
) -> None:
    """Create a confirmed external issue identity mapping."""
    global _identity_serial
    _identity_serial += 1
    if metadata is not None:
        payload = metadata
    else:
        payload = {"creator_credits": creators or []}
    identity = ExternalIdentity(
        provider=provider,
        entity_type="issue",
        external_id=f"sv-{_identity_serial}",
        metadata_json=payload,
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()


async def _rate(
    db: AsyncSession,
    issue: Issue,
    *,
    rating: float,
    timestamp: datetime,
) -> Event:
    """Create one rate event for an issue."""
    event = Event(
        type="rate",
        thread_id=issue.thread_id,
        issue_id=issue.id,
        issue_number=issue.issue_number,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    return event


@pytest.mark.asyncio
async def test_subset_projection_matches_full_library_with_manual_fallback(
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Subset SQL preserves global coverage and confirmed/manual precedence."""
    from app.repositories.creator_summary import (
        load_creator_summary_inputs,
        load_creator_summary_inputs_for_creators,
    )
    from app.services import creator_summary as service

    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Subset parity",
        issue_count=5,
        queue_position=1,
        read_through=3,
    )
    thread.manual_creator_credits = [{"name": "Manual Writer", "roles": ["writer"]}]
    await _confirm_identity(
        async_db,
        issues[0],
        creators=[{"id": 3001, "name": "Requested", "role": "writer"}],
    )
    await _confirm_identity(
        async_db,
        issues[1],
        creators=[{"id": 3002, "name": "Other", "role": "writer"}],
    )
    await _confirm_identity(async_db, issues[2], creators=[])
    await _confirm_identity(async_db, issues[3], creators=[{"id": "bad", "name": "Invalid"}])
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    await _rate(async_db, issues[1], rating=3.0, timestamp=D1)
    await _rate(async_db, issues[2], rating=5.0, timestamp=D1)
    manual_id = manual_creator_id("Manual Writer")
    requests = [{3001}, {manual_id}, {3001, 3002, manual_id}, set()]
    actual = [
        await service.get_creator_summaries(
            async_db, default_user.id, [f"creator:{cid}" for cid in ids]
        )
        for ids in requests
    ]
    full = await load_creator_summary_inputs(async_db, default_user.id)

    async def baseline(
        db: AsyncSession,
        user_id: int,
        requested_creator_ids: set[int],
    ) -> object:
        return full

    monkeypatch.setattr(service, "load_creator_summary_inputs_for_creators", baseline)
    expected = [
        await service.get_creator_summaries(
            async_db, default_user.id, [f"creator:{cid}" for cid in ids]
        )
        for ids in requests
    ]
    assert actual == expected
    projected = await load_creator_summary_inputs_for_creators(async_db, default_user.id, {3001})
    assert set(projected.owned_issues) == {issues[0].id}
    assert set(projected.effective_ratings) == {issues[0].id}
    assert projected.coverage_counts == (3, 3, 0, 0, 2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_credit",
    [
        {"id": "-7", "name": "Invalid ID"},
        {"id": 123, "name": "\t\n\r"},
        {"id": 123, "name": "\u2003\u00a0"},
        {"id": 123, "name": ""},
        {"id": 1.5, "name": "Fractional ID"},
    ],
)
async def test_unusable_confirmed_credit_keeps_manual_fallback(
    async_db: AsyncSession,
    default_user: User,
    bad_credit: dict[str, object],
) -> None:
    """SQL credit validation must not suppress manual attribution for invalid credits."""
    from app.services.creator_summary import get_creator_summaries

    thread, issues = await _make_thread(
        async_db,
        default_user,
        title="Fallback",
        issue_count=1,
        queue_position=1,
        read_through=1,
    )
    thread.manual_creator_credits = [{"name": "Manual Writer", "roles": ["writer"]}]
    await _confirm_identity(async_db, issues[0], creators=[bad_credit])
    await _rate(async_db, issues[0], rating=4.0, timestamp=D1)
    key = f"creator:{manual_creator_id('Manual Writer')}"
    response = await get_creator_summaries(async_db, default_user.id, [key])
    assert response.summaries[key].ratings_count == 1
    assert response.summaries[key].average_rating == 4.0
    assert response.coverage.rated_issues_with_creator_metadata == 1
