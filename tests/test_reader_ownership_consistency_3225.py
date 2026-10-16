"""Reader-ownership consistency at graph and library write boundaries (#3225).

Proves the closure-critical contract: cross-user graph/member/pending/
frontier writes are rejected through APIs and central service paths even
when both users share one CatalogIssue; a same-reader wrong-thread frontier
is rejected; the DB frontier constraint rejects invalid direct SQL; the
preflight detector reports without private payloads; shared catalog reads
grant no personal access.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue
from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.reading_session import ReadingSession
from app.models.tag import Tag
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services import ownership_guard
from app.services.dependency_service import create_dependency
from app.services.errors import ForbiddenError, NotFoundError
from app.services.tag_service import TagService


async def _make_thread(
    db: AsyncSession, user_id: int, title: str, queue_position: int = 1
) -> Thread:
    """Create one owned thread."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=1,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _make_issue(
    db: AsyncSession,
    thread_id: int,
    number: str = "1",
    catalog_issue_id: int | None = None,
) -> Issue:
    """Create one issue in a thread."""
    issue = Issue(
        thread_id=thread_id,
        issue_number=number,
        position=1,
        status="unread",
        catalog_issue_id=catalog_issue_id,
    )
    db.add(issue)
    await db.flush()
    return issue


async def _make_shared_catalog_issue(db: AsyncSession) -> CatalogIssue:
    """Create one CatalogIssue both readers may reference."""
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="3225-shared-1",
        metadata_json={"name": "Shared #1", "issue_number": "1"},
    )
    db.add(identity)
    await db.flush()
    catalog_issue = CatalogIssue(canonical_external_identity_id=identity.id)
    db.add(catalog_issue)
    await db.flush()
    return catalog_issue


@pytest.mark.asyncio
async def test_cross_user_dependency_rejected_despite_shared_catalog(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Cross-user dependency writes fail even with a shared CatalogIssue."""
    catalog_issue = await _make_shared_catalog_issue(db)
    thread_a = await _make_thread(db, sample_user.id, "Alice thread")
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    issue_a = await _make_issue(db, thread_a.id, catalog_issue_id=catalog_issue.id)
    issue_b = await _make_issue(db, thread_b.id, catalog_issue_id=catalog_issue.id)

    result, reason = await create_dependency(issue_a.id, issue_b.id, sample_user.id, db)
    assert result is None
    assert reason == "Issue not found"

    result, reason = await create_dependency(issue_b.id, issue_a.id, sample_user2.id, db)
    assert result is None
    assert reason == "Issue not found"

    with pytest.raises(HTTPException) as exc_info:
        await ownership_guard.require_dependency_endpoints_owned(
            db, sample_user.id, issue_a.id, issue_b.id
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_same_reader_wrong_thread_frontier_rejected(
    db: AsyncSession, sample_user
) -> None:
    """A frontier pointing at another thread of the same reader is rejected."""
    thread_a = await _make_thread(db, sample_user.id, "Series A")
    thread_b = await _make_thread(db, sample_user.id, "Series B")
    issue_b = await _make_issue(db, thread_b.id)

    with pytest.raises(HTTPException) as exc_info:
        await ownership_guard.require_frontier_in_thread(db, thread_a.id, issue_b.id)
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "frontier_issue_mismatch"

    assert (
        await ownership_guard.require_frontier_in_thread(db, thread_a.id, None)
    ) is None


@pytest.mark.asyncio
async def test_frontier_db_constraint_rejects_direct_sql(
    db: AsyncSession, sample_user
) -> None:
    """Direct SQL pointing a frontier at another thread violates the FK."""
    thread_a = await _make_thread(db, sample_user.id, "Series A")
    thread_b = await _make_thread(db, sample_user.id, "Series B")
    issue_b = await _make_issue(db, thread_b.id)

    # The shared ``db`` fixture joins an outer transaction with savepoints, so
    # a DEFERRABLE INITIALLY DEFERRED constraint would only be enforced at that
    # outer COMMIT — which the fixture rolls back and the test never reaches.
    # Flipping this one constraint to IMMEDIATE makes PostgreSQL evaluate the
    # violation while the fixture transaction is still alive. The stored
    # constraint definition (deferrable, initially deferred) is untouched.
    await db.execute(text("SET CONSTRAINTS fk_threads_frontier_same_thread IMMEDIATE"))
    with pytest.raises(IntegrityError):
        await db.execute(
            update(Thread)
            .where(Thread.id == thread_a.id)
            .values(next_unread_issue_id=issue_b.id)
        )
    await db.rollback()


@pytest.mark.asyncio
async def test_cross_user_plan_membership_rejected_despite_shared_catalog(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Plan membership for another reader's issue is rejected (422)."""
    from app.services.continuity_plan_writer import validate_node_ownership

    catalog_issue = await _make_shared_catalog_issue(db)
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    issue_b = await _make_issue(db, thread_b.id, catalog_issue_id=catalog_issue.id)

    node = ContinuityPlanNode(
        id="n1", node_type="issue", ref_id=issue_b.id, lane_id="main", position=0
    )
    with pytest.raises(HTTPException) as exc_info:
        await validate_node_ownership(db, user_id=sample_user.id, nodes=[node])
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "dangling_plan_reference"


@pytest.mark.asyncio
async def test_cross_user_plan_dependency_link_rejected(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Linking a cross-user dependency edge to a plan is rejected (422)."""
    from app.services.reading_plan_normalization import link_dependency_to_plan

    thread_a = await _make_thread(db, sample_user.id, "Alice thread")
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    issue_a = await _make_issue(db, thread_a.id)
    issue_b = await _make_issue(db, thread_b.id)
    db.add(Dependency(source_issue_id=issue_a.id, target_issue_id=issue_b.id))
    await db.flush()
    dependency = (
        await db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == issue_a.id,
                Dependency.target_issue_id == issue_b.id,
            )
        )
    ).scalar_one()

    plan = ContinuityPlan(user_id=sample_user.id, name="Alice plan")
    db.add(plan)
    await db.flush()

    with pytest.raises(HTTPException) as exc_info:
        await link_dependency_to_plan(
            db, user_id=sample_user.id, plan_id=plan.id, dependency_id=dependency.id
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "dangling_plan_reference"


@pytest.mark.asyncio
async def test_cross_user_session_pending_rejected(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Session pending pointers to another reader's rows are rejected."""
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    issue_b = await _make_issue(db, thread_b.id)
    session = ReadingSession(user_id=sample_user.id, pending_thread_id=thread_b.id)
    db.add(session)
    await db.flush()

    with pytest.raises(HTTPException) as exc_info:
        await ownership_guard.require_session_pending_consistent(db, session)
    assert exc_info.value.status_code == 422

    thread_a = await _make_thread(db, sample_user.id, "Alice thread")
    issue_a = await _make_issue(db, thread_a.id)
    session.pending_thread_id = thread_a.id
    session.pending_issue_id = issue_b.id
    with pytest.raises(HTTPException) as exc_info:
        await ownership_guard.require_session_pending_consistent(db, session)
    assert exc_info.value.status_code == 422

    session.pending_issue_id = issue_a.id
    await ownership_guard.require_session_pending_consistent(db, session)


@pytest.mark.asyncio
async def test_private_tag_cross_user_target_rejected(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """A private tag cannot be assigned to another reader's target."""
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    tag = Tag(
        name="alice-only",
        normalized_name="alice-only",
        scope="private",
        owner_user_id=sample_user.id,
        color="#FF0000",
    )
    db.add(tag)
    await db.flush()

    service = TagService(db)
    with pytest.raises(ForbiddenError):
        await service.assign_tag(sample_user, tag.id, "Thread", thread_b.id)

    owner_id = await ownership_guard.target_owner_id(db, "Thread", thread_b.id)
    assert owner_id == sample_user2.id


@pytest.mark.asyncio
async def test_shared_catalog_grants_no_personal_access(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Reading another reader's rows via shared catalog identity fails."""
    from app.services.ownership import get_owned_issue_or_404
    from app.services.thread_service import get_thread_detail

    catalog_issue = await _make_shared_catalog_issue(db)
    thread_a = await _make_thread(db, sample_user.id, "Alice private thread")
    thread_a.notes = "Alice secret notes"
    issue_a = await _make_issue(db, thread_a.id, catalog_issue_id=catalog_issue.id)
    await db.flush()

    with pytest.raises(NotFoundError):
        await get_thread_detail(db, sample_user2.id, thread_a.id)
    with pytest.raises(HTTPException):
        await get_owned_issue_or_404(db, sample_user2.id, issue_a.id)


@pytest.mark.asyncio
async def test_detect_violations_reports_without_private_payloads(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Preflight reports counts/IDs only — no titles, notes, or payloads."""
    catalog_issue = await _make_shared_catalog_issue(db)
    thread_a = await _make_thread(db, sample_user.id, "Alice thread")
    thread_b = await _make_thread(db, sample_user2.id, "Bob thread")
    issue_a = await _make_issue(db, thread_a.id, catalog_issue_id=catalog_issue.id)
    issue_b = await _make_issue(db, thread_b.id, catalog_issue_id=catalog_issue.id)
    thread_a.next_unread_issue_id = issue_a.id
    await db.flush()

    report = await ownership_guard.detect_violations(db)
    assert not report.has_violations

    # Simulate legacy drift with direct writes that bypass service validation.
    db.add(Dependency(source_issue_id=issue_a.id, target_issue_id=issue_b.id))
    plan = ContinuityPlan(user_id=sample_user.id, name="Alice plan")
    db.add(plan)
    await db.flush()
    db.add(
        ReadingPlanIssue(
            plan_id=plan.id,
            occurrence_id="drift-1",
            issue_id=issue_b.id,
            lane_id="main",
            display_position=0,
        )
    )
    await db.flush()

    drifted = await ownership_guard.detect_violations(db)
    assert drifted.has_violations
    assert drifted.cross_user_dependency_ids != []
    assert drifted.plan_issue_pairs == [[plan.id, issue_b.id]]

    payload = str(drifted.to_redacted_dict())
    assert "Alice thread" not in payload
    assert "Bob thread" not in payload
    assert "notes" not in payload.lower()
    await db.rollback()


@pytest.mark.asyncio
async def test_set_pending_thread_supersedes_cross_thread_pointer(
    db: AsyncSession, sample_user
) -> None:
    """Manual selection retargets the whole pending pair to one thread."""
    from app.services.thread_service import set_current_issue, set_pending_thread

    thread_a = await _make_thread(db, sample_user.id, "Series A")
    thread_b = await _make_thread(db, sample_user.id, "Series B")
    await _make_issue(db, thread_a.id, number="1")
    await _make_issue(db, thread_b.id, number="1")
    thread_a.total_issues = 1
    thread_b.total_issues = 1
    await db.flush()

    await set_current_issue(db, sample_user.id, thread_a.id, issue_number="1")
    await set_pending_thread(db, sample_user.id, thread_b.id)

    status = await ownership_guard.session_pending_status(
        db,
        (
            await db.execute(
                select(ReadingSession)
                .where(
                    ReadingSession.user_id == sample_user.id,
                    ReadingSession.ended_at.is_(None),
                )
                .order_by(ReadingSession.id.desc())
            )
        ).scalar_one(),
    )
    assert status.consistent
