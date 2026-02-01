#!/usr/bin/env python3
"""Fix thread position duplicates by reorganizing positions sequentially.

This script addresses the duplicate position issues found by the audit script.
"""

import asyncio
from collections import defaultdict

from sqlalchemy import select, update, func

from app.database import AsyncSessionLocal
from app.models import Thread


async def fix_thread_positions() -> None:
    """Fix thread positions by reorganizing them sequentially per-user.

    Args:
        None

    Returns:
        None

    Raises:
        Exception: If an error occurs during the database operation.
    """
    print("=== Fixing Thread Positions ===")
    print(
        "This will reorganize all active threads per-user to have sequential positions starting from 1."
    )
    print()

    async with AsyncSessionLocal() as db:
        try:
            # Get all active threads ordered by user_id, then current position (and by id as tiebreaker)
            result = await db.execute(
                select(Thread)
                .where(Thread.status == "active")
                .order_by(Thread.user_id, Thread.queue_position, Thread.id)
            )
            active_threads = result.scalars().all()

            if not active_threads:
                print("No active threads found.")
                return

            print(f"Found {len(active_threads)} active threads to reorganize.")
            print()

            # Group threads by user_id
            threads_by_user = defaultdict(list)
            for thread in active_threads:
                threads_by_user[thread.user_id].append(thread)

            # Update positions sequentially per user
            for user_id, user_threads in threads_by_user.items():
                print(f"Reorganizing {len(user_threads)} threads for user {user_id}")
                for i, thread in enumerate(user_threads, 1):
                    if thread.queue_position != i:
                        print(
                            f"  Updating Thread {thread.id}: position {thread.queue_position} -> {i}"
                        )
                        await db.execute(
                            update(Thread).where(Thread.id == thread.id).values(queue_position=i)
                        )

            await db.commit()
            print()
            print("✓ Thread positions have been reorganized successfully!")
            print()

            # Verify the fix
            print("=== Verification ===")
            result = await db.execute(
                select(Thread.user_id, Thread.queue_position, func.count(Thread.id))
                .where(Thread.status == "active")
                .group_by(Thread.user_id, Thread.queue_position)
                .having(func.count(Thread.id) > 1)
            )
            duplicates_after = result.all()

            if duplicates_after:
                print("✗ Still found duplicate positions after fix:")
                for user_id, position, count in duplicates_after:
                    print(f"  User {user_id}, Position {position}: {count} threads")
            else:
                print("✓ No duplicate positions found after fix")

        except Exception as e:
            print(f"✗ Error fixing positions: {e}")
            await db.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(fix_thread_positions())
