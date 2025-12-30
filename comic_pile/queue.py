from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Thread


def move_to_front(thread_id: int, db: Session) -> None:
    threads = (
        db.execute(select(Thread).where(Thread.queue_position >= 1).order_by(Thread.queue_position))
        .scalars()
        .all()
    )

    target_thread = next((t for t in threads if t.id == thread_id), None)
    if not target_thread:
        return

    for thread in threads:
        if thread.id == thread_id:
            thread.queue_position = 1
        elif thread.queue_position < target_thread.queue_position:
            thread.queue_position += 1

    db.commit()


def move_to_back(thread_id: int, db: Session) -> None:
    threads = (
        db.execute(select(Thread).where(Thread.queue_position >= 1).order_by(Thread.queue_position))
        .scalars()
        .all()
    )

    target_thread = next((t for t in threads if t.id == thread_id), None)
    if not target_thread:
        return

    max_position = len(threads)

    for thread in threads:
        if thread.id == thread_id:
            thread.queue_position = max_position
        elif thread.queue_position > target_thread.queue_position:
            thread.queue_position -= 1

    db.commit()


def move_to_position(thread_id: int, new_position: int, db: Session) -> None:
    threads = (
        db.execute(select(Thread).where(Thread.queue_position >= 1).order_by(Thread.queue_position))
        .scalars()
        .all()
    )

    target_thread = next((t for t in threads if t.id == thread_id), None)
    if not target_thread:
        return

    if new_position < 1:
        new_position = 1

    max_position = len(threads)
    if new_position > max_position:
        new_position = max_position

    old_position = target_thread.queue_position

    if old_position == new_position:
        return

    if old_position < new_position:
        for thread in threads:
            if thread.id == thread_id:
                thread.queue_position = new_position
            elif old_position < thread.queue_position <= new_position:
                thread.queue_position -= 1
    else:
        for thread in threads:
            if thread.id == thread_id:
                thread.queue_position = new_position
            elif new_position <= thread.queue_position < old_position:
                thread.queue_position += 1

    db.commit()


def get_roll_pool(db: Session) -> list[Thread]:
    threads = (
        db.execute(
            select(Thread)
            .where(Thread.status == "active")
            .where(Thread.queue_position >= 1)
            .order_by(Thread.queue_position)
        )
        .scalars()
        .all()
    )

    return list(threads)


def get_stale_threads(db: Session, days: int = 7) -> list[Thread]:
    cutoff_date = datetime.now() - timedelta(days=days)

    threads = (
        db.execute(
            select(Thread)
            .where(Thread.status == "active")
            .where((Thread.last_activity_at < cutoff_date) | (Thread.last_activity_at.is_(None)))
            .order_by(Thread.last_activity_at.asc().nullsfirst())
        )
        .scalars()
        .all()
    )

    return list(threads)
