"""Release source candidate discovery for the Reading Plan reader (#3930).

The reader must be able to see which ComicVine volumes a plan's threads could
follow, enable one of them, and understand why an unmapped or ambiguous thread
cannot be followed yet.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_plan(
    async_db: AsyncSession,
    *,
    user_id: int,
    nodes_json: list[dict[str, object]] | None = None,
) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name="Candidate Plan",
        ordering_mode="informational",
        nodes_json=nodes_json or [],
        lanes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    return plan


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
    thread = Thread(
        title=title,
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
    return thread


async def _add_issue(async_db: AsyncSession, *, thread: Thread, issue_number: str = "1") -> Issue:
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()
    return issue


async def _add_plan_issue(
    async_db: AsyncSession, *, plan: ContinuityPlan, issue: Issue, position: int = 0
) -> ReadingPlanIssue:
    row = ReadingPlanIssue(
        plan_id=plan.id,
        occurrence_id=f"occ-{issue.id}",
        issue_id=issue.id,
        lane_id="main",
        display_position=position,
    )
    async_db.add(row)
    await async_db.flush()
    return row


async def _make_identity(
    async_db: AsyncSession,
    *,
    external_id: str = "12345",
    provider: str = "comicvine",
    entity_type: str = "series",
    metadata: dict[str, object] | None = None,
) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        metadata_json=metadata
        if metadata is not None
        else {
            "name": "Ultimate Spider-Man",
            "publisher": "Marvel",
            "start_year": 2024,
            "count_of_issues": 12,
        },
    )
    async_db.add(identity)
    await async_db.flush()
    return identity


async def _add_mapping(
    async_db: AsyncSession,
    *,
    thread_id: int,
    identity_id: int,
    status: str = "confirmed",
) -> ThreadExternalSeriesMapping:
    mapping = ThreadExternalSeriesMapping(
        thread_id=thread_id,
        external_identity_id=identity_id,
        status=status,
        evidence_source="test",
    )
    async_db.add(mapping)
    await async_db.flush()
    return mapping


@pytest.mark.asyncio
async def test_reader_endpoint_serializes_release_candidates(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The retired v1 plan reader no longer serves release candidates."""
    user = await get_or_create_user_async(async_db)
    plan = await _make_plan(async_db, user_id=user.id)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/reader")
    assert response.status_code == 404
