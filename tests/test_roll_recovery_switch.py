"""Integration coverage for accepting blocked-roll prerequisite guidance."""

from datetime import UTC, datetime

from httpx import AsyncClient
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Session, Thread
from app.models.continuity_rule import ContinuityRule
from app.schemas.roll_recovery_switch import RollPrerequisiteSwitchRequest
from tests.conftest import get_or_create_user_async


def test_switch_request_rejects_crossover_nodes() -> None:
    """Only concrete issues belong to the prerequisite-switch contract.

    Returns:
        None.
    """
    with pytest.raises(ValidationError):
        RollPrerequisiteSwitchRequest.model_validate(
            {"node_type": "crossover", "node_id": 1},
        )


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one active issue-tracked thread with one unread issue.

    Args:
        async_db: Async test database session.
        user_id: Owner of the test thread.
        suffix: Unique suffix for the generated thread title.

    Returns:
        The created unread issue.
    """
    thread = Thread(
        title=f"Recovery {suffix}",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = issue.id
    return issue


def _item_rule(*, user_id: int, source_id: int, target_id: int) -> ContinuityRule:
    """Create one issue-to-issue item-read continuity rule.

    Args:
        user_id: Owner of the continuity rule.
        source_id: Prerequisite issue identifier.
        target_id: Blocked issue identifier.

    Returns:
        The unpersisted continuity rule.
    """
    return ContinuityRule(
        user_id=user_id,
        source_type="issue",
        source_id=source_id,
        target_type="issue",
        target_id=target_id,
        satisfaction_type="item_read",
    )


async def _set_pending_roll(auth_client: AsyncClient, thread_id: int) -> None:
    """Use the existing override flow to create an auditable pending roll.

    Args:
        auth_client: Authenticated API test client.
        thread_id: Thread to set as the pending Roll.

    Returns:
        None.
    """
    response = await auth_client.post("/api/roll/override", json={"thread_id": thread_id})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_switches_blocked_roll_to_direct_readable_prerequisite(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A direct readable prerequisite becomes active without reading the original.

    Args:
        auth_client: Authenticated API test client.
        async_db: Async test database session.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    blocked = await _make_issue(async_db, user_id=user.id, suffix="blocked")
    prerequisite = await _make_issue(async_db, user_id=user.id, suffix="prerequisite")
    async_db.add(
        _item_rule(user_id=user.id, source_id=prerequisite.id, target_id=blocked.id)
    )
    await async_db.commit()
    await _set_pending_roll(auth_client, blocked.thread_id)

    response = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": prerequisite.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["original_thread_id"] == blocked.thread_id
    assert payload["target_thread_id"] == prerequisite.thread_id
    assert payload["target_issue_id"] == prerequisite.id
    assert payload["changed"] is True

    session_result = await async_db.execute(select(Session).where(Session.user_id == user.id))
    session = session_result.scalars().first()
    assert session is not None
    await async_db.refresh(session)
    await async_db.refresh(blocked)
    await async_db.refresh(prerequisite)
    assert session.pending_thread_id == prerequisite.thread_id
    assert blocked.status == "unread"
    assert prerequisite.status == "unread"

    event_result = await async_db.execute(
        select(Event)
        .where(Event.session_id == session.id)
        .where(Event.selection_method == "dependency_recovery")
    )
    recovery_event = event_result.scalar_one()
    assert recovery_event.selected_thread_id == prerequisite.thread_id
    assert recovery_event.issue_id == prerequisite.id


@pytest.mark.asyncio
async def test_switches_to_transitive_readable_leaf(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A→B→C recovery accepts C while B remains blocked.

    Args:
        auth_client: Authenticated API test client.
        async_db: Async test database session.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    blocked = await _make_issue(async_db, user_id=user.id, suffix="transitive-a")
    middle = await _make_issue(async_db, user_id=user.id, suffix="transitive-b")
    leaf = await _make_issue(async_db, user_id=user.id, suffix="transitive-c")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=middle.id, target_id=blocked.id),
            _item_rule(user_id=user.id, source_id=leaf.id, target_id=middle.id),
        ]
    )
    await async_db.commit()
    await _set_pending_roll(auth_client, blocked.thread_id)

    response = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": leaf.id},
    )

    assert response.status_code == 200
    assert response.json()["target_issue_id"] == leaf.id
    assert response.json()["target_thread_id"] == leaf.thread_id


@pytest.mark.asyncio
async def test_duplicate_switch_is_idempotent(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A duplicate tap returns success without writing a second recovery event.

    Args:
        auth_client: Authenticated API test client.
        async_db: Async test database session.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    blocked = await _make_issue(async_db, user_id=user.id, suffix="duplicate-blocked")
    prerequisite = await _make_issue(async_db, user_id=user.id, suffix="duplicate-prerequisite")
    async_db.add(
        _item_rule(user_id=user.id, source_id=prerequisite.id, target_id=blocked.id)
    )
    await async_db.commit()
    await _set_pending_roll(auth_client, blocked.thread_id)

    first = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": prerequisite.id},
    )
    second = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": prerequisite.id},
    )

    assert first.status_code == 200
    assert first.json()["changed"] is True
    assert second.status_code == 200
    assert second.json()["changed"] is False

    session_result = await async_db.execute(select(Session.id).where(Session.user_id == user.id))
    session_id = session_result.scalars().first()
    event_count_result = await async_db.execute(
        select(func.count())
        .select_from(Event)
        .where(Event.session_id == session_id)
        .where(Event.selection_method == "dependency_recovery")
    )
    assert event_count_result.scalar_one() == 1


@pytest.mark.asyncio
async def test_rejects_stale_recommendation_after_prerequisite_becomes_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Mutation-time revalidation rejects guidance invalidated after bootstrap.

    Args:
        auth_client: Authenticated API test client.
        async_db: Async test database session.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    blocked = await _make_issue(async_db, user_id=user.id, suffix="stale-blocked")
    prerequisite = await _make_issue(async_db, user_id=user.id, suffix="stale-prerequisite")
    async_db.add(
        _item_rule(user_id=user.id, source_id=prerequisite.id, target_id=blocked.id)
    )
    await async_db.commit()
    await _set_pending_roll(auth_client, blocked.thread_id)

    prerequisite.status = "read"
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": prerequisite.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_roll_recovery"


@pytest.mark.asyncio
async def test_rejects_issue_that_was_not_recommended(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A readable but unrelated issue cannot replace the pending roll.

    Args:
        auth_client: Authenticated API test client.
        async_db: Async test database session.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    blocked = await _make_issue(async_db, user_id=user.id, suffix="unrelated-blocked")
    prerequisite = await _make_issue(async_db, user_id=user.id, suffix="unrelated-prerequisite")
    unrelated = await _make_issue(async_db, user_id=user.id, suffix="unrelated-other")
    async_db.add(
        _item_rule(user_id=user.id, source_id=prerequisite.id, target_id=blocked.id)
    )
    await async_db.commit()
    await _set_pending_roll(auth_client, blocked.thread_id)

    response = await auth_client.post(
        "/api/v1/roll/switch-prerequisite",
        json={"node_type": "issue", "node_id": unrelated.id},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_roll_recovery"
