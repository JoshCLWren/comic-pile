"""Tests for Issue Move/Reorder/Delete API."""

import pytest
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Event, Issue, Thread, User
from comic_pile.dependencies import refresh_user_blocked_status
from tests.conftest import get_or_create_user_async

async def _create_issue_tracking_thread(
    async_db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_specs: list[tuple[str, str]],
) -> tuple[Thread, list[Issue]]:
    """Create a thread with ordered issues for issue API tests."""
    unread_count = sum(1 for _, issue_status in issue_specs if issue_status == "unread")
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=unread_count,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=len(issue_specs),
        reading_progress="not_started" if unread_count == len(issue_specs) else "in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    issues: list[Issue] = []
    for position, (issue_number, issue_status) in enumerate(issue_specs, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=issue_number,
            position=position,
            status=issue_status,
            read_at=datetime.now(UTC) if issue_status == "read" else None,
        )
        issues.append(issue)

    async_db.add_all(issues)
    await async_db.flush()

    first_unread = next((issue for issue in issues if issue.status == "unread"), None)
    thread.next_unread_issue_id = first_unread.id if first_unread else None
    if first_unread is None:
        thread.reading_progress = "completed"
        thread.status = "completed"

    await async_db.commit()
    return thread, issues

async def _get_thread_issues(async_db: AsyncSession, thread_id: int) -> list[Issue]:
    """Return issues for a thread ordered by position."""
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    return list(result.scalars().all())

async def test_move_issue_to_top_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue to the top of its thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To Top Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[3].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["4", "1", "2", "3"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[3].id

async def test_move_issue_to_middle_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue into the middle of a thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To Middle Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[0].id}:move",
        json={"after_issue_id": issues[2].id},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["2", "3", "1", "4"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

async def test_move_issue_to_end_reorders_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move can move an issue to the end of a thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move To End Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[0].id}:move",
        json={"after_issue_id": issues[3].id},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["2", "3", "4", "1"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[1].id

async def test_move_issue_not_found(auth_client: AsyncClient) -> None:
    """POST /issues/{issue_id}:move returns 404 for non-existent issue."""
    response = await auth_client.post("/api/v1/issues/999:move", json={"after_issue_id": None})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

async def test_move_issue_after_issue_must_be_in_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move rejects after_issue_id values from another thread."""
    user = await get_or_create_user_async(async_db)
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Target Move Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    other_thread, other_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Other Move Thread",
        issue_specs=[("A", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{target_issues[0].id}:move",
        json={"after_issue_id": other_issues[0].id},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    target_thread_issues = await _get_thread_issues(async_db, target_thread.id)
    assert [issue.issue_number for issue in target_thread_issues] == ["1", "2", "3"]
    assert [issue.position for issue in target_thread_issues] == [1, 2, 3]

    other_thread_issues = await _get_thread_issues(async_db, other_thread.id)
    assert [issue.issue_number for issue in other_thread_issues] == ["A"]
    assert [issue.position for issue in other_thread_issues] == [1]

async def test_move_issue_recalculates_next_unread_issue_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move updates next_unread_issue_id from position order."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Next Unread Thread",
        issue_specs=[("1", "read"), ("2", "read"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/issues/{issues[3].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in reordered_issues] == ["4", "1", "2", "3"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[3].id

async def test_move_issue_refreshes_blocked_status_from_new_next_unread_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /issues/{issue_id}:move refreshes blocked flags after changing next unread."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Block Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Move Block Target Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[0].id,
        )
    )
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    response = await auth_client.post(
        f"/api/v1/issues/{target_issues[2].id}:move",
        json={"after_issue_id": None},
    )
    assert response.status_code == 204

    await async_db.refresh(target_thread)
    assert target_thread.next_unread_issue_id == target_issues[2].id
    assert target_thread.is_blocked is False

    source_issues[0].status = "read"
    source_issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False

async def test_reorder_issues_updates_positions(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder rewrites issue positions from the request order."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Bulk Reorder Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "read"), ("4", "unread")],
    )

    requested_order = [issues[2].id, issues[0].id, issues[3].id, issues[1].id]
    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": requested_order},
    )
    assert response.status_code == 204

    reordered_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.id for issue in reordered_issues] == requested_order
    assert [issue.issue_number for issue in reordered_issues] == ["3", "1", "4", "2"]
    assert [issue.position for issue in reordered_issues] == [1, 2, 3, 4]

    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[0].id

async def test_reorder_issues_refreshes_blocked_status_from_new_next_unread_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder refreshes blocked flags after reordering."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Reorder Block Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Reorder Block Target Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[0].id,
        )
    )
    await async_db.commit()

    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is True

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues:reorder",
        json={"issue_ids": [target_issues[1].id, target_issues[0].id, target_issues[2].id]},
    )
    assert response.status_code == 204

    await async_db.refresh(target_thread)
    assert target_thread.next_unread_issue_id == target_issues[1].id
    assert target_thread.is_blocked is False

    source_issues[0].status = "read"
    source_issues[0].read_at = datetime.now(UTC)
    await async_db.commit()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    await async_db.refresh(target_thread)
    assert target_thread.is_blocked is False

async def test_reorder_issues_rejects_missing_issue_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder returns 400 when request omits thread issues."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Missing IDs Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": [issues[0].id, issues[2].id]},
    )
    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"].lower()

async def test_reorder_issues_rejects_extra_issue_ids(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues:reorder returns 400 when request has extra IDs."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Extra IDs Thread",
        issue_specs=[("1", "unread"), ("2", "unread"), ("3", "unread")],
    )
    _, other_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Other Extra IDs Thread",
        issue_specs=[("A", "unread")],
    )

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues:reorder",
        json={"issue_ids": [issues[0].id, issues[1].id, issues[2].id, other_issues[0].id]},
    )
    assert response.status_code == 400
    assert "exactly once" in response.json()["detail"].lower()

async def test_delete_middle_issue_shifts_positions_and_logs_event(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} deletes a middle issue and compacts later positions."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Middle Thread",
        issue_specs=[("1", "unread"), ("2", "read"), ("3", "unread"), ("4", "unread")],
    )

    response = await auth_client.delete(f"/api/v1/issues/{issues[1].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "3", "4"]
    assert [issue.position for issue in remaining_issues] == [1, 2, 3]

    await async_db.refresh(thread)
    assert thread.total_issues == 3
    assert thread.issues_remaining == 3
    assert thread.next_unread_issue_id == issues[0].id
    assert thread.reading_progress == "not_started"
    assert thread.status == "active"

    event_result = await async_db.execute(
        select(Event).where(
            Event.thread_id == thread.id,
            Event.type == "issue_deleted",
            Event.issue_number == "2",
        )
    )
    event = event_result.scalar_one_or_none()
    assert event is not None
    assert event.type == "issue_deleted"

async def test_delete_last_issue_leaves_prior_positions_unchanged(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} leaves earlier positions unchanged when deleting the end."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Last Thread",
        issue_specs=[("1", "read"), ("2", "unread"), ("3", "read")],
    )

    response = await auth_client.delete(f"/api/v1/issues/{issues[2].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "2"]
    assert [issue.position for issue in remaining_issues] == [1, 2]

    await async_db.refresh(thread)
    assert thread.total_issues == 2
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == issues[1].id
    assert thread.reading_progress == "in_progress"

async def test_delete_next_unread_issue_advances_pointer_and_deletes_dependencies(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} advances next_unread_issue_id and removes issue dependencies."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Dependency Source Thread",
        issue_specs=[("Alpha", "unread")],
    )
    target_thread, target_issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete Next Unread Thread",
        issue_specs=[("1", "read"), ("2", "unread"), ("3", "unread"), ("4", "read")],
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issues[0].id,
            target_issue_id=target_issues[1].id,
        )
    )
    await async_db.commit()

    response = await auth_client.delete(f"/api/v1/issues/{target_issues[1].id}")
    assert response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, target_thread.id)
    assert [issue.issue_number for issue in remaining_issues] == ["1", "3", "4"]
    assert [issue.position for issue in remaining_issues] == [1, 2, 3]

    await async_db.refresh(target_thread)
    assert target_thread.next_unread_issue_id == target_issues[2].id
    assert target_thread.issues_remaining == 1
    assert target_thread.reading_progress == "in_progress"

    dependency_count_result = await async_db.execute(
        select(func.count())
        .select_from(Dependency)
        .where(Dependency.target_issue_id == target_issues[1].id)
    )
    assert dependency_count_result.scalar_one() == 0

async def test_delete_all_issues_completes_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """DELETE /issues/{issue_id} can remove the final issues and complete the thread."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _create_issue_tracking_thread(
        async_db,
        user,
        title="Delete All Issues Thread",
        issue_specs=[("1", "unread"), ("2", "unread")],
    )

    first_response = await auth_client.delete(f"/api/v1/issues/{issues[0].id}")
    assert first_response.status_code == 204

    second_response = await auth_client.delete(f"/api/v1/issues/{issues[1].id}")
    assert second_response.status_code == 204

    remaining_issues = await _get_thread_issues(async_db, thread.id)
    assert remaining_issues == []

    await async_db.refresh(thread)
    assert thread.total_issues == 0
    assert thread.issues_remaining == 0
    assert thread.next_unread_issue_id is None
    assert thread.reading_progress == "completed"
    assert thread.status == "completed"

async def test_delete_issue_not_found(auth_client: AsyncClient) -> None:
    """DELETE /issues/{issue_id} returns 404 for non-existent issues."""
    response = await auth_client.delete("/api/v1/issues/999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

