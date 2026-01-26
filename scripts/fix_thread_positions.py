#!/usr/bin/env python3
"""Fix thread position duplicates by reorganizing positions sequentially.

This script addresses the duplicate position issues found by the audit script.
"""

from sqlalchemy import select, update, func

from app.database import SessionLocal
from app.models import Thread


def fix_thread_positions() -> None:
    """Fix thread positions by reorganizing them sequentially."""
    print("=== Fixing Thread Positions ===")
    print("This will reorganize all active threads to have sequential positions starting from 1.")
    print()

    db = SessionLocal()

    try:
        # Get all active threads ordered by current position (and by id as tiebreaker)
        active_threads = (
            db.execute(
                select(Thread)
                .where(Thread.status == "active")
                .order_by(Thread.queue_position, Thread.id)
            )
            .scalars()
            .all()
        )

        if not active_threads:
            print("No active threads found.")
            return

        print(f"Found {len(active_threads)} active threads to reorganize.")
        print()

        # Update positions sequentially
        for i, thread in enumerate(active_threads, 1):
            if thread.queue_position != i:
                print(f"Updating Thread {thread.id}: position {thread.queue_position} -> {i}")
                db.execute(update(Thread).where(Thread.id == thread.id).values(queue_position=i))

        db.commit()
        print()
        print("✓ Thread positions have been reorganized successfully!")
        print()

        # Verify the fix
        print("=== Verification ===")
        duplicates_after = db.execute(
            select(Thread.queue_position, func.count(Thread.id))
            .where(Thread.status == "active")
            .group_by(Thread.queue_position)
            .having(func.count(Thread.id) > 1)
        ).all()

        if duplicates_after:
            print("✗ Still found duplicate positions after fix:")
            for position, count in duplicates_after:
                print(f"  Position {position}: {count} threads")
        else:
            print("✓ No duplicate positions found after fix")

    except Exception as e:
        print(f"✗ Error fixing positions: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix_thread_positions()
