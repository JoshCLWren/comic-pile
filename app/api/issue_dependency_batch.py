"""Batched issue-dependency API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Dependency, Issue, Thread
from app.models.user import User
from app.schemas.dependency import IssueDependenciesResponse, IssueDependencyEdge
from app.schemas.issue_dependency_batch import ThreadIssueDependenciesResponse
from app.services.ownership import get_owned_thread_or_404

router = APIRouter(prefix="/api/v1", tags=["dependencies"])


def _dependency_edge(issue: Issue, thread: Thread, dependency_id: int) -> IssueDependencyEdge:
    """Build the existing issue-edge response shape for a related issue."""
    return IssueDependencyEdge(
        dependency_id=dependency_id,
        source_issue_id=issue.id,
        source_issue_number=issue.issue_number,
        source_thread_id=thread.id,
        source_thread_title=thread.title,
    )


@router.get(
    "/threads/{thread_id}/issue-dependencies",
    response_model=ThreadIssueDependenciesResponse,
)
async def list_thread_issue_dependencies(
    thread_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ThreadIssueDependenciesResponse:
    """Return dependency edges for every issue in one thread using bulk queries.

    This endpoint replaces the frontend's previous one-request-per-issue pattern.
    Empty dependency payloads are included so clients can distinguish a complete
    response from missing data without issuing fallback requests.
    """
    await get_owned_thread_or_404(db, current_user.id, thread_id)

    thread_issue_result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position, Issue.id)
    )
    thread_issues = list(thread_issue_result.scalars().all())
    thread_issue_ids = [issue.id for issue in thread_issues]

    if not thread_issue_ids:
        return ThreadIssueDependenciesResponse(thread_id=thread_id, issues=[])

    dependency_result = await db.execute(
        select(Dependency)
        .where(
            or_(
                Dependency.source_issue_id.in_(thread_issue_ids),
                Dependency.target_issue_id.in_(thread_issue_ids),
            )
        )
        .order_by(Dependency.id)
    )
    dependencies = list(dependency_result.scalars().all())

    related_issue_ids = set(thread_issue_ids)
    for dependency in dependencies:
        if dependency.source_issue_id is not None:
            related_issue_ids.add(dependency.source_issue_id)
        if dependency.target_issue_id is not None:
            related_issue_ids.add(dependency.target_issue_id)

    related_result = await db.execute(
        select(Issue, Thread)
        .join(Thread, Thread.id == Issue.thread_id)
        .where(Issue.id.in_(related_issue_ids), Thread.user_id == current_user.id)
    )
    related_rows = related_result.all()
    issue_map = {issue.id: issue for issue, _thread in related_rows}
    thread_map = {thread.id: thread for _issue, thread in related_rows}

    incoming_by_issue: dict[int, list[IssueDependencyEdge]] = {
        issue_id: [] for issue_id in thread_issue_ids
    }
    outgoing_by_issue: dict[int, list[IssueDependencyEdge]] = {
        issue_id: [] for issue_id in thread_issue_ids
    }

    for dependency in dependencies:
        if (
            dependency.target_issue_id in incoming_by_issue
            and dependency.source_issue_id is not None
        ):
            source_issue = issue_map.get(dependency.source_issue_id)
            source_thread = thread_map.get(source_issue.thread_id) if source_issue else None
            if source_issue is not None and source_thread is not None:
                incoming_by_issue[dependency.target_issue_id].append(
                    _dependency_edge(source_issue, source_thread, dependency.id)
                )

        if (
            dependency.source_issue_id in outgoing_by_issue
            and dependency.target_issue_id is not None
        ):
            target_issue = issue_map.get(dependency.target_issue_id)
            target_thread = thread_map.get(target_issue.thread_id) if target_issue else None
            if target_issue is not None and target_thread is not None:
                outgoing_by_issue[dependency.source_issue_id].append(
                    _dependency_edge(target_issue, target_thread, dependency.id)
                )

    return ThreadIssueDependenciesResponse(
        thread_id=thread_id,
        issues=[
            IssueDependenciesResponse(
                issue_id=issue.id,
                incoming=incoming_by_issue[issue.id],
                outgoing=outgoing_by_issue[issue.id],
            )
            for issue in thread_issues
        ],
    )
