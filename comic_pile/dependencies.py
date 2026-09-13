"""Dependency logic for hard-blocking queued threads."""

from collections import defaultdict, deque

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import TTL, cached
from app.config import get_app_settings
from app.continuity_blocking import get_continuity_blocked_thread_ids
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.continuity_graph import SNAPSHOT_SESSION_KEY


def _invalidate_continuity_snapshot(user_id: int, db: AsyncSession) -> None:
    """Discard session-local graph state before an explicitly uncached evaluation."""
    session_cache = db.info.get(SNAPSHOT_SESSION_KEY)
    if isinstance(session_cache, dict):
        session_cache.pop(user_id, None)


async def _get_blocked_thread_ids_uncached(user_id: int, db: AsyncSession) -> set[int]:
    """Read unified blocked thread IDs directly from the current transaction."""
    _invalidate_continuity_snapshot(user_id, db)
    continuity_blocked_ids = await get_continuity_blocked_thread_ids(user_id, db)
    if not get_app_settings().legacy_dependency_blocking_enabled:
        return continuity_blocked_ids
    legacy_blocked_ids = await _get_legacy_blocked_thread_ids_uncached(user_id, db)
    return legacy_blocked_ids | continuity_blocked_ids


async def _get_legacy_blocked_thread_ids_uncached(user_id: int, db: AsyncSession) -> set[int]:
    """Read dependency-based blocked thread IDs directly from the current transaction."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    target_thread = Thread.__table__.alias("target_thread")
    source = Thread.__table__.alias("source_thread")

    issue_result = await db.execute(
        select(target_thread.c.id)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source, source_issue.c.thread_id == source.c.id)
        .where(target_thread.c.user_id == user_id)
        .where(source.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return {row[0] for row in issue_result.all()}


@cached(ttl=TTL.SHORT)
async def get_blocked_thread_ids(user_id: int, db: AsyncSession) -> set[int]:
    """Return cached blocked thread IDs for non-transactional reads."""
    return await _get_blocked_thread_ids_uncached(user_id, db)


class BlockingDependency:
    """A single dependency blocking a thread, described in reader language."""

    def __init__(self, thread_id: int, thread_title: str, issue_number: str) -> None:
        """Store blocker identity and derive the reader-facing label."""
        self.thread_id = thread_id
        self.thread_title = thread_title
        self.issue_number = str(issue_number)
        self.label = build_blocking_explanation(issue_number, thread_title)


def build_blocking_explanation(issue_number: str, thread_title: str) -> str:
    """Return the shared human-readable blocked-by sentence for one dependency edge.

    This is the single copy generator for dependency blocking sentences so the
    queue's blocked list and reader-context edge rows stay word-for-word
    consistent app-wide. Reader-facing explanations identify comics with human
    identity only; raw internal database identifiers must never be rendered.

    Args:
        issue_number: Issue number of the blocking source issue.
        thread_title: Title of the thread owning the source issue.

    Returns:
        A concise blocked-by sentence.
    """
    return f"Blocked by {thread_title}: #{issue_number}"


def format_blocking_reason(dependency: BlockingDependency) -> str:
    """Legacy plain-text reason retained for backward-compatible consumers."""
    return build_blocking_explanation(dependency.issue_number, dependency.thread_title)


def _merge_blocking_explanations(
    *groups: list[BlockingDependency],
) -> list[BlockingDependency]:
    """Deduplicate blocker rows while preserving first-seen order."""
    merged: list[BlockingDependency] = []
    seen: set[tuple[int, str]] = set()
    for group in groups:
        for dependency in group:
            key = (dependency.thread_id, dependency.issue_number)
            if key in seen:
                continue
            seen.add(key)
            merged.append(dependency)
    return merged


async def _legacy_blocking_explanations(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[BlockingDependency]:
    """Return unread raw-Dependency blockers for one thread."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")

    issue_result = await db.execute(
        select(
            source_thread.c.id,
            source_thread.c.title,
            source_issue.c.id,
            source_issue.c.issue_number,
        )
        .select_from(target_thread)
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(target_thread.c.id == thread_id)
        .where(target_thread.c.user_id == user_id)
        .where(source_thread.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
        .distinct()
    )
    return [
        BlockingDependency(
            thread_id=thread_id_val,
            thread_title=thread_title,
            issue_number=str(issue_number),
        )
        for thread_id_val, thread_title, _issue_id, issue_number in issue_result.all()
    ]


async def _legacy_blocking_explanations_batch(
    thread_ids: list[int],
    user_id: int,
    db: AsyncSession,
) -> dict[int, list[BlockingDependency]]:
    """Return unread raw-Dependency blockers for many threads."""
    source_issue = Issue.__table__.alias("source_issue")
    next_unread_issue = Issue.__table__.alias("next_unread_issue")
    source_thread = Thread.__table__.alias("source_thread")
    target_thread = Thread.__table__.alias("target_thread")

    result = await db.execute(
        select(
            target_thread.c.id,
            source_thread.c.id,
            source_thread.c.title,
            source_issue.c.id,
            source_issue.c.issue_number,
        )
        .join(
            next_unread_issue,
            next_unread_issue.c.id == target_thread.c.next_unread_issue_id,
        )
        .join(Dependency, Dependency.target_issue_id == next_unread_issue.c.id)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(source_thread, source_issue.c.thread_id == source_thread.c.id)
        .where(target_thread.c.id.in_(thread_ids))
        .where(target_thread.c.user_id == user_id)
        .where(source_thread.c.user_id == user_id)
        .where(source_issue.c.status != "read")
        .where(target_thread.c.next_unread_issue_id.isnot(None))
    )

    reasons_map: dict[int, list[BlockingDependency]] = {}
    for target_tid, src_tid, src_title, _src_iid, src_issue_num in result.all():
        reasons_map.setdefault(target_tid, []).append(
            BlockingDependency(
                thread_id=src_tid,
                thread_title=src_title,
                issue_number=str(src_issue_num),
            )
        )
    return reasons_map


async def _continuity_blocking_explanations(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[BlockingDependency]:
    """Convert continuity-graph blockers into shared reader-facing explanations."""
    from app.services.continuity_graph import issue_readiness, load_snapshot

    _invalidate_continuity_snapshot(user_id, db)
    snapshot = await load_snapshot(db, user_id)
    thread = snapshot.threads.get(thread_id)
    if thread is None or thread.next_unread_issue_id is None:
        return []

    reasons: list[BlockingDependency] = []
    seen: set[tuple[int, str]] = set()
    for blocker in issue_readiness(thread.next_unread_issue_id, snapshot):
        for detail in blocker.unread_issue_details:
            issue = snapshot.issues.get(detail.issue_id)
            if issue is None:
                continue
            source_thread = snapshot.threads.get(issue.thread_id)
            if source_thread is None:
                continue
            key = (source_thread.id, str(issue.issue_number))
            if key in seen:
                continue
            seen.add(key)
            reasons.append(
                BlockingDependency(
                    thread_id=source_thread.id,
                    thread_title=source_thread.title,
                    issue_number=str(issue.issue_number),
                )
            )
    return reasons


async def _continuity_blocking_explanations_batch(
    thread_ids: list[int],
    user_id: int,
    db: AsyncSession,
) -> dict[int, list[BlockingDependency]]:
    """Convert continuity-graph blockers for many threads in one snapshot load."""
    from app.services.continuity_graph import issue_readiness, load_snapshot

    _invalidate_continuity_snapshot(user_id, db)
    snapshot = await load_snapshot(db, user_id)
    reasons_map: dict[int, list[BlockingDependency]] = {}
    for thread_id in thread_ids:
        thread = snapshot.threads.get(thread_id)
        if thread is None or thread.next_unread_issue_id is None:
            continue
        reasons: list[BlockingDependency] = []
        seen: set[tuple[int, str]] = set()
        for blocker in issue_readiness(thread.next_unread_issue_id, snapshot):
            for detail in blocker.unread_issue_details:
                issue = snapshot.issues.get(detail.issue_id)
                if issue is None:
                    continue
                source_thread = snapshot.threads.get(issue.thread_id)
                if source_thread is None:
                    continue
                key = (source_thread.id, str(issue.issue_number))
                if key in seen:
                    continue
                seen.add(key)
                reasons.append(
                    BlockingDependency(
                        thread_id=source_thread.id,
                        thread_title=source_thread.title,
                        issue_number=str(issue.issue_number),
                    )
                )
        if reasons:
            reasons_map[thread_id] = reasons
    return reasons_map


async def get_blocking_explanations(thread_id: int, user_id: int, db: AsyncSession) -> list[BlockingDependency]:
    """Human-readable reasons a thread is blocked.

    Continuity-rule blockers are always included so reader-facing copy stays
    accurate after the raw-Dependency Roll switch is disabled. Legacy
    Dependency rows are included only while
    ``LEGACY_DEPENDENCY_BLOCKING_ENABLED`` remains true.
    """
    continuity = await _continuity_blocking_explanations(thread_id, user_id, db)
    if not get_app_settings().legacy_dependency_blocking_enabled:
        return continuity
    legacy = await _legacy_blocking_explanations(thread_id, user_id, db)
    return _merge_blocking_explanations(continuity, legacy)


async def get_blocking_explanations_batch(
    thread_ids: list[int],
    user_id: int,
    db: AsyncSession,
) -> dict[int, list[BlockingDependency]]:
    """Human-readable blocking reasons for multiple threads in one query."""
    if not thread_ids:
        return {}

    continuity_map = await _continuity_blocking_explanations_batch(thread_ids, user_id, db)
    if not get_app_settings().legacy_dependency_blocking_enabled:
        return {thread_id: continuity_map.get(thread_id, []) for thread_id in thread_ids}

    legacy_map = await _legacy_blocking_explanations_batch(thread_ids, user_id, db)
    return {
        thread_id: _merge_blocking_explanations(
            continuity_map.get(thread_id, []),
            legacy_map.get(thread_id, []),
        )
        for thread_id in thread_ids
    }


async def validate_position_dependency_consistency(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[str]:
    """Return warnings where in-thread dependency order conflicts with issue positions."""
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    thread = Thread.__table__.alias("thread")

    result = await db.execute(
        select(
            thread.c.title,
            source_issue.c.issue_number,
            source_issue.c.position,
            target_issue.c.issue_number,
            target_issue.c.position,
        )
        .select_from(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .join(thread, source_issue.c.thread_id == thread.c.id)
        .where(thread.c.id == thread_id)
        .where(thread.c.user_id == user_id)
        .where(target_issue.c.thread_id == thread.c.id)
        .where(source_issue.c.position >= target_issue.c.position)
        .order_by(source_issue.c.position, target_issue.c.position, Dependency.id)
    )

    return [
        (
            f'In thread "{thread_title}", issue #{source_issue_number} '
            f"(position {source_position}) blocks issue #{target_issue_number} "
            f"(position {target_position}). Position is canonical for in-thread order."
        )
        for (
            thread_title,
            source_issue_number,
            source_position,
            target_issue_number,
            target_position,
        ) in result.all()
    ]


async def detect_circular_dependency(
    source_id: int,
    target_id: int,
    dependency_type: str,
    db: AsyncSession,
) -> bool:
    """Return True if adding source->target would introduce a cycle."""
    if source_id == target_id:
        return True

    if dependency_type == "issue":
        result = await db.execute(select(Dependency.source_issue_id, Dependency.target_issue_id))
    else:
        return False

    adjacency: dict[int, set[int]] = defaultdict(set)
    for src, tgt in result.all():
        if src is None or tgt is None:
            continue
        adjacency[src].add(tgt)

    queue = deque([target_id])
    visited: set[int] = set()

    while queue:
        node = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        if node == source_id:
            return True
        queue.extend(adjacency.get(node, set()))

    return False


async def get_dependency_order_conflicts(
    thread_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[dict]:
    """Return structured conflicts where dependency order disagrees with issue position order.

    Args:
        thread_id: Thread to check for conflicts.
        user_id: Authenticated user ID for ownership validation.
        db: Database session.

    Returns:
        List of conflict dictionaries with issue details and dependency requirements.
    """
    source_issue = Issue.__table__.alias("source_issue")
    target_issue = Issue.__table__.alias("target_issue")
    thread = Thread.__table__.alias("thread")

    result = await db.execute(
        select(
            thread.c.id,
            thread.c.title,
            source_issue.c.id.label("source_issue_id"),
            source_issue.c.issue_number.label("source_issue_number"),
            source_issue.c.position.label("source_position"),
            target_issue.c.id.label("target_issue_id"),
            target_issue.c.issue_number.label("target_issue_number"),
            target_issue.c.position.label("target_position"),
        )
        .select_from(Dependency)
        .join(source_issue, Dependency.source_issue_id == source_issue.c.id)
        .join(target_issue, Dependency.target_issue_id == target_issue.c.id)
        .join(thread, source_issue.c.thread_id == thread.c.id)
        .where(thread.c.id == thread_id)
        .where(thread.c.user_id == user_id)
        .where(target_issue.c.thread_id == thread.c.id)
        .where(source_issue.c.position >= target_issue.c.position)
        .order_by(source_issue.c.position, target_issue.c.position, Dependency.id)
    )

    conflicts: list[dict] = []
    for row in result.all():
        conflicts.append(
            {
                "issue_id": row.source_issue_id,
                "issue_number": row.source_issue_number,
                "position": row.source_position,
                "dependency_requires_before": [
                    {
                        "issue_id": row.target_issue_id,
                        "issue_number": row.target_issue_number,
                        "position": row.target_position,
                    }
                ],
                "conflict": f"position {row.source_position} comes after issue at position {row.target_position}, but dependency says it must come before",
            }
        )

    return conflicts


async def update_thread_blocked_status(thread_id: int, user_id: int, db: AsyncSession) -> None:
    """Recalculate one thread's denormalized blocked flag from the unified evaluator."""
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.user_id == user_id)
        .values(is_blocked=thread_id in blocked_ids)
    )


async def refresh_user_blocked_status(
    user_id: int,
    db: AsyncSession,
) -> dict[int, bool]:
    """Recalculate unified blocked flags and return prior values that changed.

    Args:
        user_id: Thread owner.
        db: Database session.

    Returns:
        Mapping of changed thread IDs to their previous blocked flag.
    """
    blocked_ids = await _get_blocked_thread_ids_uncached(user_id, db)

    candidate_filter = Thread.is_blocked.is_(True)
    if blocked_ids:
        candidate_filter = or_(candidate_filter, Thread.id.in_(blocked_ids))

    result = await db.execute(
        select(Thread.id, Thread.is_blocked)
        .where(Thread.user_id == user_id)
        .where(candidate_filter)
    )
    prior_values = {row.id: row.is_blocked for row in result.all()}
    changes = {
        thread_id: old_value
        for thread_id, old_value in prior_values.items()
        if old_value != (thread_id in blocked_ids)
    }

    to_unblock = [thread_id for thread_id in changes if thread_id not in blocked_ids]
    if to_unblock:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_unblock))
            .values(is_blocked=False)
        )

    to_block = [thread_id for thread_id in changes if thread_id in blocked_ids]
    if to_block:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_block))
            .values(is_blocked=True)
        )

    return changes


async def refresh_legacy_blocked_status(
    user_id: int,
    db: AsyncSession,
) -> dict[int, bool]:
    """Recalculate dependency-based blocked flags and return prior values that changed.

    Args:
        user_id: Thread owner.
        db: Database session.

    Returns:
        Mapping of changed thread IDs to their previous blocked flag.
    """
    blocked_ids = await _get_legacy_blocked_thread_ids_uncached(user_id, db)

    candidate_filter = Thread.is_blocked.is_(True)
    if blocked_ids:
        candidate_filter = or_(candidate_filter, Thread.id.in_(blocked_ids))

    result = await db.execute(
        select(Thread.id, Thread.is_blocked)
        .where(Thread.user_id == user_id)
        .where(candidate_filter)
    )
    prior_values = {row.id: row.is_blocked for row in result.all()}
    changes = {
        thread_id: old_value
        for thread_id, old_value in prior_values.items()
        if old_value != (thread_id in blocked_ids)
    }

    to_unblock = [thread_id for thread_id in changes if thread_id not in blocked_ids]
    if to_unblock:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_unblock))
            .values(is_blocked=False)
        )

    to_block = [thread_id for thread_id in changes if thread_id in blocked_ids]
    if to_block:
        await db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.id.in_(to_block))
            .values(is_blocked=True)
        )

    return changes
