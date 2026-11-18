"""Dependency business logic and orchestration.

Services own business rules and transaction boundaries (commit/rollback/retry).
Query construction lives in ``app/repositories/dependency_repository.py`` and
sibling repositories; HTTP status mapping lives in routers.
"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread
from app.repositories import dependency_repository, issue_repository
from app.schemas.dependency import (
    DependencyResponse,
    IssueDependenciesResponse,
    IssueDependencyEdge,
    ThreadDependenciesResponse,
)
from app.schemas.issue_dependency_batch import ThreadIssueDependenciesResponse
from comic_pile.dependencies import (
    get_blocked_thread_ids,
)


async def enrich_dependencies(deps: list[Dependency], db: AsyncSession) -> list[DependencyResponse]:
    """Batch-enrich dependencies with human-readable labels.

    Collects all referenced issue/thread IDs, fetches them in bulk,
    then builds DependencyResponse objects from the lookup dicts.
    """
    if not deps:
        return []

    # Collect all IDs we need to look up
    issue_ids: set[int] = set()
    thread_ids: set[int] = set()
    for dep in deps:
        if dep.source_issue_id is not None:
            issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            issue_ids.add(dep.target_issue_id)

    # Bulk fetch issues
    issue_map: dict[int, Issue] = {}
    if issue_ids:
        result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        for issue in result.scalars():
            issue_map[issue.id] = issue
            # We'll also need the parent threads for issue labels
            thread_ids.add(issue.thread_id)

    # Bulk fetch threads
    thread_map: dict[int, Thread] = {}
    if thread_ids:
        result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        for thread in result.scalars():
            thread_map[thread.id] = thread

    # Build enriched responses
    responses: list[DependencyResponse] = []
    for dep in deps:
        source_label: str | None = None
        target_label: str | None = None
        source_issue_thread_id: int | None = None
        target_issue_thread_id: int | None = None

        if dep.source_issue_id is not None:
            source_issue = issue_map.get(dep.source_issue_id)
            if source_issue:
                source_issue_thread_id = source_issue.thread_id
                source_thread = thread_map.get(source_issue.thread_id)
                if source_thread:
                    source_label = f"{source_thread.title} #{source_issue.issue_number}"

        if dep.target_issue_id is not None:
            target_issue = issue_map.get(dep.target_issue_id)
            if target_issue:
                target_issue_thread_id = target_issue.thread_id
                target_thread = thread_map.get(target_issue.thread_id)
                if target_thread:
                    target_label = f"{target_thread.title} #{target_issue.issue_number}"

        response = DependencyResponse.model_validate(dep, from_attributes=True)
        response.source_label = source_label
        response.target_label = target_label
        response.source_issue_thread_id = source_issue_thread_id
        response.target_issue_thread_id = target_issue_thread_id
        response.source_thread_id = source_issue_thread_id
        response.target_thread_id = target_issue_thread_id
        response.is_issue_level = True
        responses.append(response)

    return responses


async def get_all_blocked_thread_ids(
    user_id: int, db: AsyncSession
) -> list[int]:
    """Return all currently blocked thread IDs for the current user."""
    blocked_ids = await get_blocked_thread_ids(user_id, db)
    return sorted(blocked_ids)


async def get_thread_dependencies(
    thread_id: int, user_id: int, db: AsyncSession
) -> ThreadDependenciesResponse | None:
    """List dependencies where a thread blocks others and where it is blocked."""
    from app.repositories import thread_repository
    
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    blocking_deps, blocked_by_deps = await dependency_repository.get_thread_dependencies(
        db, thread_id
    )

    all_deps = list(blocking_deps) + list(blocked_by_deps)
    enriched = await enrich_dependencies(all_deps, db)
    blocking_count = len(blocking_deps)

    return ThreadDependenciesResponse(
        blocking=enriched[:blocking_count],
        blocked_by=enriched[blocking_count:],
    )


async def get_issue_dependencies(
    issue_id: int, user_id: int, db: AsyncSession
) -> IssueDependenciesResponse | None:
    """List all incoming and outgoing dependency edges for a specific issue."""
    issue = await issue_repository.get_issue(db, issue_id)
    if not issue:
        return None

    thread = await db.get(Thread, issue.thread_id)
    if not thread or thread.user_id != user_id:
        return None

    incoming_deps, outgoing_deps = await dependency_repository.get_issue_dependencies(
        db, issue_id
    )

    all_deps = list(incoming_deps) + list(outgoing_deps)

    issue_ids: set[int] = set()
    thread_ids: set[int] = {issue.thread_id}
    for dep in all_deps:
        if dep.source_issue_id is not None:
            issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            issue_ids.add(dep.target_issue_id)

    issue_map: dict[int, Issue] = {}
    if issue_ids:
        result = await db.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        for issue_obj in result.scalars():
            issue_map[issue_obj.id] = issue_obj
            thread_ids.add(issue_obj.thread_id)

    thread_map: dict[int, Thread] = {}
    if thread_ids:
        result = await db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        for thread_obj in result.scalars():
            thread_map[thread_obj.id] = thread_obj

    incoming_edges: list[IssueDependencyEdge] = []
    outgoing_edges: list[IssueDependencyEdge] = []

    for dep in incoming_deps:
        if dep.source_issue_id is not None:
            source_issue = issue_map.get(dep.source_issue_id)
            if source_issue:
                source_thread = thread_map.get(source_issue.thread_id)
                if source_thread and source_thread.user_id == user_id:
                    incoming_edges.append(
                        IssueDependencyEdge(
                            dependency_id=dep.id,
                            source_issue_id=source_issue.id,
                            source_issue_number=source_issue.issue_number,
                            source_thread_id=source_thread.id,
                            source_thread_title=source_thread.title,
                        )
                    )

    for dep in outgoing_deps:
        if dep.target_issue_id is not None:
            target_issue = issue_map.get(dep.target_issue_id)
            if target_issue:
                target_thread = thread_map.get(target_issue.thread_id)
                if target_thread and target_thread.user_id == user_id:
                    outgoing_edges.append(
                        IssueDependencyEdge(
                            dependency_id=dep.id,
                            source_issue_id=target_issue.id,
                            source_issue_number=target_issue.issue_number,
                            source_thread_id=target_thread.id,
                            source_thread_title=target_thread.title,
                        )
                    )

    return IssueDependenciesResponse(
        issue_id=issue_id,
        incoming=incoming_edges,
        outgoing=outgoing_edges,
    )


async def get_thread_issue_dependencies_batch(
    thread_id: int, user_id: int, db: AsyncSession
) -> ThreadIssueDependenciesResponse | None:
    """Get all dependencies for issues in one thread using bulk queries.

    Args:
        thread_id: Thread to get dependencies for.
        user_id: Thread owner.
        db: Database session.

    Returns:
        Thread issue dependencies response, or None if thread not found.
    """
    from app.repositories import issue_repository, thread_repository

    # Verify thread ownership
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    # Get all issues in the thread
    thread_issues = await issue_repository.get_issues_by_thread(db, thread_id)
    if not thread_issues:
        return ThreadIssueDependenciesResponse(thread_id=thread_id, issues=[])

    thread_issue_ids = [issue.id for issue in thread_issues]

    # Get all dependencies involving these issues
    all_deps = await dependency_repository.get_issue_dependencies_batch(db, thread_issue_ids)

    # Build maps for related issues and threads
    related_issue_ids: set[int] = set(thread_issue_ids)
    for dep in all_deps:
        if dep.source_issue_id is not None:
            related_issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            related_issue_ids.add(dep.target_issue_id)

    # Get all related issues and their threads
    all_issues = await issue_repository.get_issues_by_ids(db, list(related_issue_ids))
    issue_map = {issue.id: issue for issue in all_issues}

    thread_ids = {issue.thread_id for issue in all_issues}
    thread_map = await thread_repository.threads_by_ids(db, thread_ids)

    # Build dependency edges
    incoming_by_issue: dict[int, list[IssueDependencyEdge]] = {
        issue_id: [] for issue_id in thread_issue_ids
    }
    outgoing_by_issue: dict[int, list[IssueDependencyEdge]] = {
        issue_id: [] for issue_id in thread_issue_ids
    }

    for dep in all_deps:
        source_issue_id = dep.source_issue_id
        target_issue_id = dep.target_issue_id

        # Handle incoming dependencies
        if (
            target_issue_id is not None
            and target_issue_id in incoming_by_issue
            and source_issue_id is not None
        ):
            source_issue = issue_map.get(source_issue_id)
            source_thread = thread_map.get(source_issue.thread_id) if source_issue else None
            if (
                source_issue is not None
                and source_thread is not None
                and source_thread.user_id == user_id
            ):
                incoming_by_issue[target_issue_id].append(
                    IssueDependencyEdge(
                        dependency_id=dep.id,
                        source_issue_id=source_issue.id,
                        source_issue_number=source_issue.issue_number,
                        source_thread_id=source_thread.id,
                        source_thread_title=source_thread.title,
                    )
                )

        # Handle outgoing dependencies
        if (
            source_issue_id is not None
            and source_issue_id in outgoing_by_issue
            and target_issue_id is not None
        ):
            target_issue = issue_map.get(target_issue_id)
            target_thread = thread_map.get(target_issue.thread_id) if target_issue else None
            if (
                target_issue is not None
                and target_thread is not None
                and target_thread.user_id == user_id
            ):
                outgoing_by_issue[source_issue_id].append(
                    IssueDependencyEdge(
                        dependency_id=dep.id,
                        source_issue_id=target_issue.id,
                        source_issue_number=target_issue.issue_number,
                        source_thread_id=target_thread.id,
                        source_thread_title=target_thread.title,
                    )
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
