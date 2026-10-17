"""Persistence for stable owner-scoped prerequisites on existing dependencies."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Dependency, Issue, Thread


async def list_owned(db: AsyncSession, user_id: int) -> list[Dependency]:
    """Return both-endpoint-owned edges, including unclassified historical rows."""
    source = aliased(Issue)
    target = aliased(Issue)
    source_thread = aliased(Thread)
    target_thread = aliased(Thread)
    result = await db.scalars(
        select(Dependency)
        .join(source, source.id == Dependency.source_issue_id)
        .join(source_thread, source_thread.id == source.thread_id)
        .join(target, target.id == Dependency.target_issue_id)
        .join(target_thread, target_thread.id == target.thread_id)
        .where(source_thread.user_id == user_id, target_thread.user_id == user_id)
        .order_by(Dependency.id)
    )
    return list(result.all())


async def add_reader(
    db: AsyncSession, source_issue_id: int, target_issue_id: int, note: str | None
) -> Dependency:
    """Insert an explicitly reader-authored edge without list ownership."""
    row = Dependency(
        source_issue_id=source_issue_id,
        target_issue_id=target_issue_id,
        note=note,
        origin="reader",
        classification="A",
        provenance="Reader-authored through explicit prerequisite API",
    )
    db.add(row)
    await db.flush()
    return row


async def promote_reader(db: AsyncSession, row: Dependency, note: str | None) -> None:
    """Activate an existing archived edge only on an explicit reader POST."""
    row.origin = "reader"
    row.classification = "A"
    row.provenance = "Reader-authored through explicit prerequisite API"
    if note is not None:
        row.note = note
    await db.flush()


async def remove(db: AsyncSession, row: Dependency) -> None:
    """Remove one already-authorized reader requirement."""
    await db.delete(row)
    await db.flush()


async def update_note(db: AsyncSession, row: Dependency, note: str | None) -> None:
    """Persist reader prose after service authorization."""
    row.note = note
    await db.flush()
