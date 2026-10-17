"""Compact per-action rating delta regression tests (issue #3226).

Proves a one-issue rating records only the issue records that actually changed
instead of repeating the rated thread's full issue collection, so the payload
stays bounded as the thread grows.
"""

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CatalogIssue,
    Event,
    ExternalIdentity,
    Issue,
    ReadingSession,
    Snapshot,
    Thread,
    User,
)
from app.services.snapshot_contract import (
    ISSUE_CHANGES_KEY,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
)

# Matches the acceptance contract: a one-issue rating on a 10,000-issue thread.
LARGE_THREAD_ISSUE_COUNT = 10_000
# The compact delta is a handful of small records, regardless of thread size.
BOUNDED_PAYLOAD_BYTES = 2_000


async def _latest_snapshot(db: AsyncSession, session_id: int) -> Snapshot:
    """Return the newest snapshot for a session."""
    result = await db.execute(
        select(Snapshot)
        .where(Snapshot.session_id == session_id)
        .order_by(Snapshot.id.desc())
    )
    snapshot = result.scalars().first()
    assert snapshot is not None
    return snapshot


def _full_collection_bytes(issue_count: int) -> int:
    """Return the bytes a full issue-state collection of ``issue_count`` needs."""
    return len(
        json.dumps(
            [
                {
                    "id": 1_000_000 + number,
                    "number": str(number),
                    "status": "unread",
                    "read_at": None,
                    "position": number,
                }
                for number in range(1, issue_count + 1)
            ]
        )
    )


@pytest.mark.asyncio
async def test_one_issue_rating_on_large_thread_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A one-issue rating stores only the changed issue, not the collection.

    Args:
        auth_client: Authenticated HTTP test client.
        async_db: Test database session.
        default_user: Authenticated test user.

    Returns:
        None.
    """
    session = ReadingSession(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Large Series",
        format="comic",
        issues_remaining=LARGE_THREAD_ISSUE_COUNT,
        total_issues=LARGE_THREAD_ISSUE_COUNT,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(number),
            position=number,
            status="unread",
        )
        for number in range(1, LARGE_THREAD_ISSUE_COUNT + 1)
    ]
    async_db.add_all(issues)
    await async_db.flush()

    first_issue = issues[0]
    first_issue_id = first_issue.id
    thread.next_unread_issue_id = first_issue_id
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            issue_id=first_issue_id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    assert snapshot.thread_states[SNAPSHOT_VERSION_KEY] == SNAPSHOT_VERSION
    state = snapshot.thread_states[str(thread.id)]

    # The compact delta never repeats the unchanged issue collection.
    assert "issue_states" not in state
    assert ISSUE_CHANGES_KEY in state
    assert [change["id"] for change in state[ISSUE_CHANGES_KEY]] == [first_issue_id]

    # Measured bytes are bounded and far below the full collection payload.
    payload_bytes = len(json.dumps(state))
    assert payload_bytes <= BOUNDED_PAYLOAD_BYTES
    assert payload_bytes < _full_collection_bytes(LARGE_THREAD_ISSUE_COUNT) // 100

    await async_db.refresh(first_issue)
    assert first_issue.status == "read"

    undo_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200

    await async_db.refresh(first_issue)
    assert first_issue.status == "unread"
    assert first_issue.read_at is None

    remaining = await async_db.scalar(
        select(func.count()).select_from(Issue).where(Issue.thread_id == thread.id)
    )
    assert remaining == LARGE_THREAD_ISSUE_COUNT


@pytest.mark.asyncio
async def test_rating_undo_preserves_catalog_link(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A catalog-linked issue keeps its catalog link through rate + undo (#3226).

    Acceptance criterion #4: creation/deletion undo preserves IDs, ownership and
    any catalog links; catalog data is never deleted by personal undo.
    """
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="catalog-1",
        metadata_json={"name": "Cataloged Issue"},
    )
    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    async_db.add_all([ext_identity, catalog_issue])
    await async_db.flush()

    session = ReadingSession(
        start_die=6,
        user_id=default_user.id,
        started_at=datetime.now(UTC),
    )
    thread = Thread(
        title="Cataloged Series",
        format="comic",
        issues_remaining=3,
        total_issues=3,
        reading_progress="in_progress",
        queue_position=1,
        status="active",
        user_id=default_user.id,
    )
    async_db.add_all([session, thread])
    await async_db.commit()
    await async_db.refresh(session)
    await async_db.refresh(thread)

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="unread",
            catalog_issue_id=catalog_issue.id,
        ),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
        Issue(thread_id=thread.id, issue_number="3", position=3, status="unread"),
    ]
    async_db.add_all(issues)
    await async_db.flush()
    await async_db.refresh(issues[0])

    rated_issue_id = issues[0].id
    thread.next_unread_issue_id = rated_issue_id
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=thread.id,
            issue_id=rated_issue_id,
            die=6,
            result=1,
        )
    )
    await async_db.commit()

    rate_response = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 5.0, "issues_read": 1},
    )
    assert rate_response.status_code == 200

    snapshot = await _latest_snapshot(async_db, session.id)
    state = snapshot.thread_states[str(thread.id)]

    # The compact delta records the catalog link in the issue preimage.
    assert ISSUE_CHANGES_KEY in state
    assert state[ISSUE_CHANGES_KEY][0]["catalog_issue_id"] == catalog_issue.id

    await async_db.refresh(issues[0])
    assert issues[0].status == "read"

    undo_response = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_response.status_code == 200

    await async_db.refresh(issues[0])
    assert issues[0].status == "unread"
    assert issues[0].read_at is None
    # The catalog link survives personal undo.
    assert issues[0].catalog_issue_id == catalog_issue.id
