"""Acceptance tests for the #3359 Roll cutover forecast.

Simulates ``c25530000001`` pair selection (native item_read + converged union
existing canonical Dependencies) and the blocked-frontier refresh. Historical
``cbl-order:%`` rows stay inert.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from app.services.roll_cutover_forecast import (
    explain_frontier_prerequisites,
    forecast_roll_eligibility,
)


def _sync_connection() -> sa.Connection:
    """Open a sync psycopg connection to the test database."""
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql+psycopg")
    engine = sa.create_engine(url)
    return engine.connect()


async def _user(db: AsyncSession, username: str) -> User:
    user = User(username=username, created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


async def _queued_thread(
    db: AsyncSession,
    user_id: int,
    title: str,
    numbers: list[str],
    *,
    is_blocked: bool,
    queue_position: int,
) -> tuple[Thread, list[Issue]]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active",
        total_issues=len(numbers),
        issues_remaining=len(numbers),
        reading_progress="unstarted",
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues: list[Issue] = []
    for position, number in enumerate(numbers, start=1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status="unread",
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


@pytest.mark.asyncio
async def test_forecast_item_read_and_converged_keep_threads_blocked(
    async_db_committed: AsyncSession,
) -> None:
    """Unread native item_read and converged rules stay blocking after backfill."""
    db = async_db_committed
    user = await _user(db, "forecast-block-rules")
    blocked_item, (item_target,) = await _queued_thread(
        db, user.id, "Item Target", ["1"], is_blocked=True, queue_position=1
    )
    blocked_conv, (conv_target,) = await _queued_thread(
        db, user.id, "Converged Target", ["1"], is_blocked=True, queue_position=2
    )
    _src_item_thread, (item_source,) = await _queued_thread(
        db, user.id, "Item Source", ["1"], is_blocked=False, queue_position=3
    )
    _src_conv_thread, (conv_source,) = await _queued_thread(
        db, user.id, "Converged Source", ["1"], is_blocked=False, queue_position=4
    )
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=item_source.id,
            target_type="issue",
            target_id=item_target.id,
            satisfaction_type="item_read",
        )
    )
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=conv_target.id,
            target_type="issue",
            target_id=conv_target.id,
            satisfaction_type="converged",
            convergence_targets=[{"type": "issue", "id": conv_source.id}],
        )
    )
    await db.commit()

    with _sync_connection() as bind:
        forecast = forecast_roll_eligibility(bind, user.id)
        explained = explain_frontier_prerequisites(
            bind, user.id, [blocked_item.id, blocked_conv.id]
        )

    assert forecast["blocked_item_read_only"] == 1
    assert forecast["blocked_converged_only"] == 1
    assert blocked_item.id not in forecast["newly_available"]
    assert blocked_conv.id not in forecast["newly_available"]
    by_id = {row["thread_id"]: row for row in explained}
    assert by_id[blocked_item.id]["item_read"][0]["source_title"] == "Item Source"
    assert by_id[blocked_conv.id]["converged"][0]["source_title"] == "Converged Source"


@pytest.mark.asyncio
async def test_forecast_cbl_order_only_becomes_newly_available(
    async_db_committed: AsyncSession,
) -> None:
    """A thread flagged blocked only by inert cbl-order becomes eligible."""
    db = async_db_committed
    user = await _user(db, "forecast-cbl-only")
    flagged, (target,) = await _queued_thread(
        db, user.id, "CBL Flagged", ["9"], is_blocked=True, queue_position=1
    )
    _src_thread, (source,) = await _queued_thread(
        db, user.id, "CBL Source", ["8"], is_blocked=False, queue_position=2
    )
    db.add(
        Dependency(
            source_issue_id=source.id,
            target_issue_id=target.id,
            note="cbl-order:source:9:1",
        )
    )
    await db.commit()

    with _sync_connection() as bind:
        forecast = forecast_roll_eligibility(bind, user.id)
        explained = explain_frontier_prerequisites(bind, user.id, [flagged.id])

    assert forecast["newly_available"] == [flagged.id]
    assert forecast["newly_blocked"] == []
    assert forecast["rollable_after"] == 2
    assert explained[0]["canonical"] == []
    assert explained[0]["item_read"] == []
    assert explained[0]["converged"] == []
    assert explained[0]["cbl_order_unread"][0]["source_title"] == "CBL Source"


@pytest.mark.asyncio
async def test_forecast_currently_eligible_stays_eligible_with_zero_newly_blocked(
    async_db_committed: AsyncSession,
) -> None:
    """Today's eligible frontiers with no unread live prereq stay rollable."""
    db = async_db_committed
    user = await _user(db, "forecast-eligible-stays")
    eligible, (target,) = await _queued_thread(
        db, user.id, "Already Eligible", ["1"], is_blocked=False, queue_position=1
    )
    canonical_blocked, (canon_target,) = await _queued_thread(
        db, user.id, "Canonical Blocked", ["1"], is_blocked=True, queue_position=2
    )
    _src_thread, (canon_source,) = await _queued_thread(
        db, user.id, "Canonical Source", ["1"], is_blocked=False, queue_position=3
    )
    db.add(
        Dependency(
            source_issue_id=canon_source.id,
            target_issue_id=canon_target.id,
            note="Magneto War recorded gate",
        )
    )
    _cbl_only, (cbl_target,) = await _queued_thread(
        db, user.id, "CBL Only Flagged", ["1"], is_blocked=True, queue_position=4
    )
    db.add(
        Dependency(
            source_issue_id=canon_source.id,
            target_issue_id=cbl_target.id,
            note="cbl-order:source:22:1",
        )
    )
    del target
    await db.commit()

    with _sync_connection() as bind:
        forecast = forecast_roll_eligibility(bind, user.id)
        explained = explain_frontier_prerequisites(
            bind, user.id, [eligible.id, canonical_blocked.id]
        )

    assert eligible.id not in forecast["newly_blocked"]
    assert forecast["newly_blocked"] == []
    assert canonical_blocked.id not in forecast["newly_available"]
    assert forecast["blocked_canonical"] == 1
    by_id = {row["thread_id"]: row for row in explained}
    assert by_id[canonical_blocked.id]["canonical"][0]["source_title"] == "Canonical Source"
    assert by_id[eligible.id]["canonical"] == []
    assert by_id[eligible.id]["item_read"] == []
    assert by_id[eligible.id]["converged"] == []
