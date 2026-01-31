#!/usr/bin/env python3
"""Test script to simulate thread repositioning with proper authentication."""

import asyncio
import sys

sys.path.insert(0, str(__file__).rsplit("/", 1)[0])

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import AsyncSessionLocal
from app.models import Thread, User


async def test_thread_reposition() -> None:
    """Test thread repositioning using the queue API logic.

    Returns:
        None
    """
    # Create database session
    async with AsyncSessionLocal() as db:
        try:
            # Find user 250
            result = await db.execute(select(User).where(User.id == 250))
            user = result.scalar_one_or_none()
            if not user:
                print("User 250 not found")
                return

            print(f"Found user: {user.username} (ID: {user.id})")

            # Get current thread state
            result = await db.execute(select(Thread).where(Thread.id == 210))
            thread = result.scalar_one_or_none()
            if not thread:
                print("Thread 210 not found")
                return

            if thread.user_id != user.id:
                print(f"Thread 210 belongs to user {thread.user_id}, not user {user.id}")
                return

            print(f"Current state: {thread.title} at position {thread.queue_position}")

            # Test the repositioning using the actual queue logic
            from comic_pile.queue import move_to_position

            old_position = thread.queue_position
            new_position = 11

            print(
                f"Attempting to move thread 210 from position {old_position} to position {new_position}"
            )

            # Call the actual function used by the API
            await move_to_position(thread.id, user.id, new_position, db)

            # Refresh and verify
            await db.refresh(thread)

            if thread.queue_position == new_position:
                print(f"✅ SUCCESS: Thread moved to position {thread.queue_position}")

                # Create reorder event like the API does
                from datetime import datetime, UTC
                from app.models import Event

                reorder_event = Event(
                    type="reorder",
                    timestamp=datetime.now(UTC),
                    thread_id=thread.id,
                )
                db.add(reorder_event)
                await db.commit()
                print("✅ SUCCESS: Reorder event created")

            else:
                print(
                    f"❌ FAILURE: Thread position is {thread.queue_position}, expected {new_position}"
                )

        except SQLAlchemyError as e:
            print(f"❌ DATABASE ERROR: {e}")
            await db.rollback()
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_thread_reposition())
