"""Regression coverage for source-backed issue materialization state."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.continuity_plan import ContinuityPlan
from app.services.cbl_plan_adoption import _ensure_missing_issue_created
from app.services.cbl_targeted_plan_adoption import _adoption_lane_id
from tests.conftest import get_or_create_user_async


def _fact(series: str, number: str) -> dict[str, object]:
    return {
        "series_name": series,
        "issue_number": number,
        "comicvine_issue_id": None,
        "external_series_identity_id": None,
    }


@pytest.mark.asyncio
async def test_materialized_series_uses_thread_local_positions_and_rollable_state(
    async_db: AsyncSession,
) -> None:
    """New source-backed series enter the queue with canonical issue tracking."""
    user = await get_or_create_user_async(async_db, "cbl-materialized-series")
    async_db.add(
        Thread(
            user_id=user.id,
            title="Existing queue item",
            format="comic",
            queue_position=3,
            status="active",
            issues_remaining=1,
            created_at=datetime.now(UTC),
        )
    )
    await async_db.flush()

    first = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("B.P.R.D.: Garden of Souls", "1"),
        volume_year=2007,
    )
    second = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("B.P.R.D.: Garden of Souls", "2"),
        volume_year=2007,
    )

    thread = await async_db.scalar(
        select(Thread).where(
            Thread.user_id == user.id,
            Thread.title == "CBL: B.P.R.D.: Garden of Souls (2007)",
        )
    )
    assert thread is not None
    issues = list(
        (
            await async_db.execute(
                select(Issue)
                .where(Issue.thread_id == thread.id)
                .order_by(Issue.position, Issue.id)
            )
        ).scalars().all()
    )
    assert [issue.id for issue in issues] == [first.id, second.id]
    assert [issue.position for issue in issues] == [1, 2]
    assert thread.queue_position == 4
    assert thread.total_issues == 2
    assert thread.issues_remaining == 2
    assert thread.next_unread_issue_id == first.id
    assert thread.reading_progress == "not_started"
    assert thread.status == "active"


@pytest.mark.asyncio
async def test_materialization_appends_to_existing_thread_and_recomputes_tracking(
    async_db: AsyncSession,
) -> None:
    """Appending missing material reactivates and recomputes an existing thread."""
    user = await get_or_create_user_async(async_db, "cbl-existing-series")
    thread = Thread(
        user_id=user.id,
        title="CBL: B.P.R.D.: The Universal Machine (2006)",
        format="comic",
        queue_position=2,
        status="completed",
        total_issues=1,
        issues_remaining=0,
        reading_progress="completed",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add(
        Issue(
            thread_id=thread.id,
            issue_number="1",
            position=7,
            status="read",
            read_at=datetime.now(UTC),
        )
    )
    await async_db.flush()

    created = await _ensure_missing_issue_created(
        async_db,
        user.id,
        fact=_fact("B.P.R.D.: The Universal Machine", "2"),
        volume_year=2006,
    )

    assert created.thread_id == thread.id
    assert created.position == 8
    assert thread.total_issues == 2
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == created.id
    assert thread.reading_progress == "in_progress"
    assert thread.status == "active"


def test_targeted_adoption_selects_existing_tail_lane_without_repairing_nodes() -> None:
    """Targeted adoption chooses the tail lane before creating new plan nodes."""
    plan = cast(
        ContinuityPlan,
        SimpleNamespace(
            lanes_json=[
                {"id": "secondary", "name": "Secondary", "order": 1},
                {"id": "main", "name": "Main", "order": 0},
            ],
            nodes_json=[
                {"id": "a", "lane_id": "main", "position": 0},
                {"id": "b", "lane_id": "secondary", "position": 9},
            ],
        ),
    )

    assert _adoption_lane_id(plan) == "secondary"
