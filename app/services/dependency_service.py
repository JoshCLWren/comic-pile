"""Dependency business logic and orchestration.

Services own business rules, transaction boundaries (commit/rollback/retry),
and cache invalidation. Query construction lives in
``app/repositories/dependency_repository.py`` and sibling repositories; HTTP
status mapping lives in routers.
"""


from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_invalidation import invalidate_user_view
from app.models import Dependency, Issue, Thread
from app.repositories import dependency_repository, issue_repository
from app.schemas.dependency import (
    BlockingDependency,
    BlockingExplanation,
    ConnectedThreadInfo,
    DependencyResponse,
    IssueDependenciesResponse,
    IssueDependencyEdge,
    ThreadDependenciesResponse,
    ThreadConnectedResponse,
)
from comic_pile.dependencies import (
    BlockingDependency as InternalBlockingDependency,
    detect_circular_dependency,
    format_blocking_reason,
    get_blocked_thread_ids,
    get_blocking_explanations,
    get_blocking_explanations_batch,
    get_dependency_order_conflicts,
    refresh_user_blocked_status,
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


def _to_blocking_dependency_schema(
    dependency: InternalBlockingDependency,
) -> BlockingDependency:
    """Convert an internal blocking dependency into its API schema form."""
    return BlockingDependency(
        thread_id=dependency.thread_id,
        thread_title=dependency.thread_title,
        issue_number=dependency.issue_number,
        label=dependency.label,
    )


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


async def get_thread_blocking_info(
    thread_id: int, user_id: int, db: AsyncSession
) -> BlockingExplanation | None:
    """Return blocked status and human-readable blocking reasons for a thread."""
    from app.repositories import thread_repository
    
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    blocked_ids = await get_blocked_thread_ids(user_id, db)
    if thread_id not in blocked_ids:
        return BlockingExplanation(is_blocked=False, blocking_reasons=[], blocking_dependencies=[])

    dependencies = await get_blocking_explanations(thread_id, user_id, db)
    return BlockingExplanation(
        is_blocked=True,
        blocking_reasons=[format_blocking_reason(dep) for dep in dependencies],
        blocking_dependencies=[_to_blocking_dependency_schema(dep) for dep in dependencies],
    )


async def get_threads_blocking_info(
    thread_ids: list[int], user_id: int, db: AsyncSession
) -> dict[int, BlockingExplanation] | None:
    """Return blocked status and human-readable blocking reasons for multiple threads.

    Args:
        thread_ids: Owned thread IDs to inspect.
        user_id: Thread owner.
        db: Database session.

    Returns:
        Mapping of thread ID to blocking explanation, or ``None`` when one or
        more threads are missing or owned by another user.
    """
    thread_count = await db.scalar(
        select(func.count()).select_from(Thread).where(
            Thread.id.in_(thread_ids),
            Thread.user_id == user_id,
        )
    )
    if thread_count != len(thread_ids):
        return None

    blocked_ids = await get_blocked_thread_ids(user_id, db)
    reasons_map = await get_blocking_explanations_batch(
        thread_ids, user_id, db
    )

    result: dict[int, BlockingExplanation] = {}
    for tid in thread_ids:
        if tid in blocked_ids:
            dependencies = reasons_map.get(tid, [])
            result[tid] = BlockingExplanation(
                is_blocked=True,
                blocking_reasons=[format_blocking_reason(dep) for dep in dependencies],
                blocking_dependencies=[_to_blocking_dependency_schema(dep) for dep in dependencies],
            )
        else:
            result[tid] = BlockingExplanation(
                is_blocked=False,
                blocking_reasons=[],
                blocking_dependencies=[],
            )

    return result


async def create_dependency(
    source_issue_id: int, target_issue_id: int, user_id: int, db: AsyncSession
) -> tuple[DependencyResponse | None, str | None]:
    """Create a hard-block dependency between owned threads or owned issues."""
    from app.repositories import issue_repository, thread_repository
    
    # Validate both issues exist and belong to the user
    source_issue = await issue_repository.get_issue(db, source_issue_id)
    target_issue = await issue_repository.get_issue(db, target_issue_id)
    if not source_issue or not target_issue:
        return None, "Issue not found"

    source_thread = await thread_repository.find_owned(db, user_id, source_issue.thread_id)
    target_thread = await thread_repository.find_owned(db, user_id, target_issue.thread_id)
    if not source_thread or not target_thread:
        return None, "Issue not found"

    # Check for circular dependency
    if await detect_circular_dependency(
        source_issue_id, target_issue_id, "issue", db
    ):
        return None, "Cannot create dependency: would create circular dependency"

    # Check if dependency already exists
    existing = await dependency_repository.get_dependency_by_ids(db, source_issue_id, target_issue_id)
    if existing:
        return None, "Dependency already exists"

    warning: str | None = None
    if target_thread.next_unread_issue_id is not None:
        next_unread_issue = await issue_repository.get_issue(db, target_thread.next_unread_issue_id)
        if next_unread_issue is not None and target_issue.position < next_unread_issue.position:
            return None, (
                f"Target issue #{target_issue.issue_number} has already been read"
                f" in {target_thread.title} (current next unread:"
                f" #{next_unread_issue.issue_number}). This dependency would"
                f" never activate. Did you mean to target issue"
                f" #{next_unread_issue.issue_number}?"
            )
        if next_unread_issue is not None and target_issue.position > next_unread_issue.position:
            issues_ahead = target_issue.position - next_unread_issue.position
            issue_word = "issue" if issues_ahead == 1 else "issues"
            warning = (
                f"Target issue #{target_issue.issue_number} is not yet the next"
                f" unread (current next unread: #{next_unread_issue.issue_number})."
                f" This dependency will block when the target thread reaches it in"
                f" {issues_ahead} {issue_word}."
            )

    try:
        dependency = await dependency_repository.create_dependency(
            db, source_issue_id, target_issue_id
        )

        await refresh_user_blocked_status(user_id, db)

        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        if "uq_dependency_issue_edge" in str(error.orig):
            return None, "Dependency already exists"
        raise

    await invalidate_dependency_caches(user_id)

    dependency = await dependency_repository.get_dependency_by_ids(
        db, source_issue_id, target_issue_id
    )

    enriched = await enrich_dependencies([dependency], db)
    response = enriched[0]
    response.warning = warning
    return response, warning


async def get_dependency(
    dependency_id: int, user_id: int, db: AsyncSession
) -> DependencyResponse | None:
    """Fetch a single dependency owned by the current user."""
    dependency = await dependency_repository.get_dependency(db, dependency_id)
    if not dependency:
        return None
    
    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, user_id, db)
    if not is_owned:
        return None
    
    enriched = await enrich_dependencies([dependency], db)
    return enriched[0]


async def update_dependency_note(
    dependency_id: int, note: str | None, user_id: int, db: AsyncSession
) -> DependencyResponse | None:
    """Update the note on a dependency owned by the current user."""
    dependency = await dependency_repository.get_dependency(db, dependency_id)
    if not dependency:
        return None
    
    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, user_id, db)
    if not is_owned:
        return None

    await dependency_repository.update_dependency_note(db, dependency_id, note)
    await db.commit()
    dependency = await dependency_repository.get_dependency(db, dependency_id)
    await invalidate_dependency_caches(user_id)
    enriched = await enrich_dependencies([dependency], db)
    return enriched[0]


async def delete_dependency(dependency_id: int, user_id: int, db: AsyncSession) -> bool:
    """Delete a dependency and refresh denormalized blocked flags."""
    dependency = await dependency_repository.get_dependency(db, dependency_id)
    if not dependency:
        return False
    
    is_owned = await dependency_repository.is_dependency_owned_by_user(dependency, user_id, db)
    if not is_owned:
        return False

    await dependency_repository.delete_dependency(db, dependency_id)
    await refresh_user_blocked_status(user_id, db)
    await db.commit()
    await invalidate_dependency_caches(user_id)
    return True


async def check_thread_dependency_order(
    thread_id: int, user_id: int, db: AsyncSession
) -> list[dict] | None:
    """Check for conflicts between dependency order and issue position order.

    Args:
        thread_id: Thread to inspect.
        user_id: Thread owner.
        db: Database session.

    Returns:
        List of conflict dictionaries, or ``None`` when the thread is missing
        or owned by another user.
    """
    from app.repositories import thread_repository
    
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    raw_conflicts = await get_dependency_order_conflicts(thread_id, user_id, db)
    return raw_conflicts


async def get_thread_connected_threads(
    thread_id: int, user_id: int, db: AsyncSession
) -> ThreadConnectedResponse | None:
    """Return threads connected to this one via dependencies."""
    from app.repositories import thread_repository
    
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    blocking_deps, blocked_by_deps = await dependency_repository.get_thread_connected_dependencies(
        db, thread_id
    )
    all_deps = blocking_deps + blocked_by_deps
    if not all_deps:
        return ThreadConnectedResponse(thread_id=thread_id, connected_threads=[])

    issue_ids = set()
    for dep in all_deps:
        if dep.source_issue_id is not None:
            issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            issue_ids.add(dep.target_issue_id)

    issue_map: dict[int, Issue] = {}
    thread_ids: set[int] = set()
    if issue_ids:
        result = await db.execute(
            select(Issue).where(Issue.id.in_(issue_ids))
        )
        for issue_obj in result.scalars():
            issue_map[issue_obj.id] = issue_obj
            thread_ids.add(issue_obj.thread_id)

    thread_map: dict[int, Thread] = {}
    if thread_ids:
        result = await db.execute(
            select(Thread).where(Thread.id.in_(thread_ids)).where(Thread.user_id == user_id)
        )
        for thread_obj in result.scalars():
            thread_map[thread_obj.id] = thread_obj

    # Track unique connected threads by thread_id, aggregating connection types.
    connected_by_thread: dict[int, dict] = {}

    for dep in blocking_deps:
        if dep.target_issue_id is not None:
            target_issue_obj = issue_map.get(dep.target_issue_id)
            if target_issue_obj:
                target_thread_obj = thread_map.get(target_issue_obj.thread_id)
                if target_thread_obj and target_issue_obj.thread_id != thread_id:
                    tid = target_thread_obj.id
                    if tid not in connected_by_thread:
                        connected_by_thread[tid] = {
                            "thread_id": tid,
                            "title": target_thread_obj.title,
                            "types": {"blocks"},
                            "dependency_ids": {dep.id},
                            "issue_number": target_issue_obj.issue_number,
                        }
                    else:
                        connected_by_thread[tid]["types"].add("blocks")
                        connected_by_thread[tid]["dependency_ids"].add(dep.id)

    for dep in blocked_by_deps:
        if dep.source_issue_id is not None:
            source_issue_obj = issue_map.get(dep.source_issue_id)
            if source_issue_obj:
                source_thread_obj = thread_map.get(source_issue_obj.thread_id)
                if source_thread_obj and source_issue_obj.thread_id != thread_id:
                    tid = source_thread_obj.id
                    if tid not in connected_by_thread:
                        connected_by_thread[tid] = {
                            "thread_id": tid,
                            "title": source_thread_obj.title,
                            "types": {"blocked_by"},
                            "dependency_ids": {dep.id},
                            "issue_number": source_issue_obj.issue_number,
                        }
                    else:
                        connected_by_thread[tid]["types"].add("blocked_by")
                        connected_by_thread[tid]["dependency_ids"].add(dep.id)

    connected: list[ConnectedThreadInfo] = []
    for entry in connected_by_thread.values():
        types = entry["types"]
        if types == {"blocks"}:
            connection_type = "blocks"
        elif types == {"blocked_by"}:
            connection_type = "blocked_by"
        else:
            connection_type = "blocks & blocked_by"
        connected.append(ConnectedThreadInfo(
            thread_id=entry["thread_id"],
            title=entry["title"],
            connection_type=connection_type,
            dependency_id=min(entry["dependency_ids"]),
            issue_number=entry["issue_number"],
        ))

    return ThreadConnectedResponse(thread_id=thread_id, connected_threads=connected)


async def invalidate_dependency_caches(user_id: int) -> None:
    """Invalidate dependency-derived views with one bounded user generation bump."""
    await invalidate_user_view(user_id)


async def get_thread_issue_dependencies_batch(
    thread_id: int, user_id: int, db: AsyncSession
) -> ThreadDependenciesResponse | None:
    """Get all dependencies for issues in one thread using bulk queries.

    Args:
        thread_id: Thread to get dependencies for.
        user_id: Thread owner.
        db: Database session.

    Returns:
        Thread dependencies response with all issue dependencies, or None if thread not found.
    """
    from app.repositories import thread_repository, issue_repository
    
    # Verify thread ownership
    thread = await thread_repository.find_owned(db, user_id, thread_id)
    if not thread:
        return None

    # Get all issues in the thread
    thread_issues = await issue_repository.get_issues_by_thread(db, thread_id)
    if not thread_issues:
        return ThreadDependenciesResponse(
            thread_id=thread_id,
            blocking=[],
            blocked_by=[]
        )
    
    thread_issue_ids = [issue.id for issue in thread_issues]

    # Get all dependencies involving these issues
    all_deps = await dependency_repository.get_issue_dependencies_batch(db, thread_issue_ids)

    # Build maps for related issues and threads
    related_issue_ids = set(thread_issue_ids)
    for dep in all_deps:
        if dep.source_issue_id is not None:
            related_issue_ids.add(dep.source_issue_id)
        if dep.target_issue_id is not None:
            related_issue_ids.add(dep.target_issue_id)

    # Get all related issues and their threads
    all_issues = await issue_repository.get_issues_by_ids(db, list(related_issue_ids))
    issue_map = {issue.id: issue for issue in all_issues}
    
    thread_ids = {issue.thread_id for issue in all_issues}
    all_threads = await thread_repository.get_threads_by_ids(db, list(thread_ids))
    thread_map = {thread.id: thread for thread in all_threads}

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
        if (target_issue_id is not None and target_issue_id in incoming_by_issue 
            and source_issue_id is not None):
            source_issue = issue_map.get(source_issue_id)
            source_thread = thread_map.get(source_issue.thread_id) if source_issue else None
            if source_issue is not None and source_thread is not None:
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
        if (source_issue_id is not None and source_issue_id in outgoing_by_issue 
            and target_issue_id is not None):
            target_issue = issue_map.get(target_issue_id)
            target_thread = thread_map.get(target_issue.thread_id) if target_issue else None
            if target_issue is not None and target_thread is not None:
                outgoing_by_issue[source_issue_id].append(
                    IssueDependencyEdge(
                        dependency_id=dep.id,
                        source_issue_id=target_issue.id,
                        source_issue_number=target_issue.issue_number,
                        source_thread_id=target_thread.id,
                        source_thread_title=target_thread.title,
                    )
                )

    return ThreadDependenciesResponse(
        thread_id=thread_id,
        blocking=outgoing_by_issue,
        blocked_by=incoming_by_issue,
    )
