"""Release source candidate discovery for the Reading Plan reader (#3930).

The reader must be able to see which ComicVine volumes a plan's threads could
follow, enable one of them, and understand why an unmapped or ambiguous thread
cannot be followed yet.
"""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
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
from app.schemas.reading_plan_release_source import ReleaseSourceCreate
from app.services import reading_plan_reader as reader_service
from app.services import reading_plan_release_source_service as release_service
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


async def _make_thread(
    async_db: AsyncSession, *, user_id: int, title: str
) -> Thread:
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


async def _add_issue(
    async_db: AsyncSession, *, thread: Thread, issue_number: str = "1"
) -> Issue:
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
async def test_confirmed_mapping_is_an_enableable_candidate(
    async_db: AsyncSession,
) -> None:
    """A confirmed ComicVine series mapping is offered as an enableable candidate."""
    user = await get_or_create_user_async(async_db, "candidate-confirmed@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Spider-Man")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db)
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.thread_id == thread.id
    assert candidate.thread_title == "Spider-Man"
    assert candidate.mapping_state == "confirmed"
    assert candidate.enableable is True
    assert candidate.followed is False
    assert candidate.external_identity_id == identity.id
    assert candidate.provider_volume_id == identity.external_id
    assert candidate.provider_title == "Ultimate Spider-Man"
    assert candidate.provider_publisher == "Marvel"
    assert candidate.provider_start_year == 2024
    assert candidate.provider_issue_count == 12


@pytest.mark.asyncio
async def test_followed_volume_is_not_offered_again(async_db: AsyncSession) -> None:
    """A volume the plan already follows is not offered as a new candidate."""
    user = await get_or_create_user_async(async_db, "candidate-followed@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Spider-Man")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db)
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    await release_service.create_source(
        async_db,
        data=ReleaseSourceCreate(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
        ),
        user_id=user.id,
    )

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert candidates == []


@pytest.mark.asyncio
async def test_undecided_mapping_is_reported_as_ambiguous(
    async_db: AsyncSession,
) -> None:
    """An unconfirmed mapping is never enableable and keeps its pending status."""
    user = await get_or_create_user_async(async_db, "candidate-ambiguous@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="X-Men")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db, external_id="777")
    await _add_mapping(
        async_db, thread_id=thread.id, identity_id=identity.id, status="candidate"
    )
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.mapping_state == "ambiguous"
    assert candidate.enableable is False
    assert candidate.mapping_status == "candidate"
    assert candidate.external_identity_id == identity.id
    assert candidate.provider_title == "Ultimate Spider-Man"


@pytest.mark.asyncio
async def test_thread_without_mapping_is_reported_as_unmapped(
    async_db: AsyncSession,
) -> None:
    """A thread with no ComicVine series mapping is reported as unmapped."""
    user = await get_or_create_user_async(async_db, "candidate-unmapped@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Unmapped")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.mapping_state == "unmapped"
    assert candidate.enableable is False
    assert candidate.external_identity_id is None
    assert candidate.provider_volume_id is None


@pytest.mark.asyncio
async def test_rejected_mapping_is_not_offered_as_ambiguous(
    async_db: AsyncSession,
) -> None:
    """A rejected mapping is not a pending decision, so the thread reads unmapped."""
    user = await get_or_create_user_async(async_db, "candidate-rejected@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Rejected")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db, external_id="888")
    await _add_mapping(
        async_db, thread_id=thread.id, identity_id=identity.id, status="rejected"
    )
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    assert candidates[0].mapping_state == "unmapped"
    assert candidates[0].enableable is False


@pytest.mark.asyncio
async def test_non_comicvine_identity_is_never_a_candidate(
    async_db: AsyncSession,
) -> None:
    """Only ComicVine series identities can become release sources."""
    user = await get_or_create_user_async(async_db, "candidate-other-provider@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Other Provider")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(
        async_db, external_id="999", provider="other", entity_type="series"
    )
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    assert candidates[0].mapping_state == "unmapped"
    assert candidates[0].enableable is False


@pytest.mark.asyncio
async def test_thread_node_reference_is_a_candidate_source(
    async_db: AsyncSession,
) -> None:
    """A whole-series thread node is part of the plan even without plan issues."""
    user = await get_or_create_user_async(async_db, "candidate-thread-node@test.com")
    thread = await _make_thread(async_db, user_id=user.id, title="Node Thread")
    identity = await _make_identity(async_db, external_id="4242")
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    plan = await _make_plan(
        async_db,
        user_id=user.id,
        nodes_json=[
            {
                "id": "node-1",
                "node_type": "thread",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 0,
            }
        ],
    )
    await async_db.commit()

    candidates = await release_service.list_release_candidates_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(candidates) == 1
    assert candidates[0].thread_id == thread.id
    assert candidates[0].enableable is True


@pytest.mark.asyncio
async def test_candidates_are_scoped_to_the_plan_owner(
    async_db: AsyncSession,
) -> None:
    """Another user cannot read a plan's release source candidates."""
    owner = await get_or_create_user_async(async_db, "candidate-owner@test.com")
    other = await get_or_create_user_async(async_db, "candidate-other@test.com")
    plan = await _make_plan(async_db, user_id=owner.id)
    await async_db.commit()

    with pytest.raises(HTTPException) as excinfo:
        await release_service.list_release_candidates_for_reader(
            async_db, plan_id=plan.id, user_id=other.id
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_reader_view_exposes_release_candidates(
    async_db: AsyncSession,
) -> None:
    """The plan reader view carries the candidate volumes with the sources."""
    user = await get_or_create_user_async(async_db, "candidate-reader-view@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Reader Candidate")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db, external_id="31337")
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    view = await reader_service.get_reading_plan_reader(
        async_db, user_id=user.id, plan_id=plan.id
    )
    assert len(view.release_candidates) == 1
    candidate = view.release_candidates[0]
    assert candidate.thread_id == thread.id
    assert candidate.enableable is True
    assert candidate.provider_volume_id == identity.external_id


@pytest.mark.asyncio
async def test_reader_endpoint_serializes_release_candidates(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The reader endpoint returns the candidate volumes a reader can enable."""
    user = await get_or_create_user_async(async_db)
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="HTTP Candidate")
    issue = await _add_issue(async_db, thread=thread)
    await _add_plan_issue(async_db, plan=plan, issue=issue)
    identity = await _make_identity(async_db, external_id="5150")
    await _add_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/reader")
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["release_candidates"]) == 1
    candidate = body["release_candidates"][0]
    assert candidate["thread_id"] == thread.id
    assert candidate["mapping_state"] == "confirmed"
    assert candidate["enableable"] is True
    assert candidate["provider_volume_id"] == identity.external_id
    assert candidate["provider_title"] == "Ultimate Spider-Man"
    assert body["release_sources"] == []

