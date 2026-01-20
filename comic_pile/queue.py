"""Queue management functions."""

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Thread


def move_to_front(thread_id: int, user_id: int, db: Session) -> None:
    """Move thread to front of queue."""
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position
    if original_position == 1:
        return

    db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.queue_position >= 1)
        .where(Thread.queue_position < original_position)
        .values(queue_position=Thread.queue_position + 1)
    )
    target_thread.queue_position = 1
    db.commit()


def move_to_back(thread_id: int, user_id: int, db: Session) -> None:
    """Move thread to back of queue."""
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()
    if not target_thread:
        return

    original_position = target_thread.queue_position

    max_position = db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position.desc())
        .limit(1)
    ).scalar()

    if max_position is None:
        return

    if original_position == max_position:
        return

    db.execute(
        update(Thread)
        .where(Thread.user_id == user_id)
        .where(Thread.queue_position > original_position)
        .values(queue_position=Thread.queue_position - 1)
    )
    target_thread.queue_position = max_position
    db.commit()


def move_to_position(thread_id: int, user_id: int, new_position: int, db: Session) -> None:
    """Move thread to specific position."""
    target_thread = db.execute(
        select(Thread).where(Thread.id == thread_id).where(Thread.user_id == user_id)
    ).scalar_one_or_none()
    if not target_thread:
        return

    old_position = target_thread.queue_position

    if new_position < 1:
        new_position = 1

    max_position = db.execute(
        select(Thread.queue_position)
        .where(Thread.user_id == user_id)
        .where(Thread.queue_position >= 1)
        .order_by(Thread.queue_position.desc())
        .limit(1)
    ).scalar()

    if max_position is None:  # pragma: no cover - impossible if target_thread exists
        max_position = 0

    if new_position > max_position:
        new_position = max_position

    if old_position == new_position:
        return

    if old_position < new_position:
        db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.queue_position > old_position)
            .where(Thread.queue_position <= new_position)
            .values(queue_position=Thread.queue_position - 1)
        )
        target_thread.queue_position = new_position
    else:
        db.execute(
            update(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.queue_position >= new_position)
            .where(Thread.queue_position < old_position)
            .where(Thread.id != thread_id)
            .values(queue_position=Thread.queue_position + 1)
        )
        target_thread.queue_position = new_position

    db.commit()


def get_roll_pool(user_id: int, db: Session) -> list[Thread]:
    """Get all active threads ordered by position."""
    threads = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    return list(threads)


def get_stale_threads(user_id: int, db: Session, days: int = 7) -> list[Thread]:
    """Get threads not read in specified days."""
    cutoff_date = datetime.now() - timedelta(days=days)

    threads = (
        db.execute(
            select(Thread)
            .where(Thread.user_id == user_id)
            .where(Thread.status == "active")
            .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
            .order_by(Thread.last_activity_at.asc().nullsfirst())
        )
        .scalars()
        .all()
    )

    return list(threads)
