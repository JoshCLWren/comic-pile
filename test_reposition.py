#!/usr/bin/env python3
"""Test script to simulate thread repositioning with proper authentication."""

import sys
from pathlib import Path

from app.database import SessionLocal
from app.models import Thread, User


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def test_thread_reposition():
    """Test thread repositioning using the queue API logic."""
    # Create database session
    db = SessionLocal()

    try:
        # Find user 250
        user = db.get(User, 250)
        if not user:
            print("User 250 not found")
            return

        print(f"Found user: {user.username} (ID: {user.id})")

        # Get current thread state
        thread = db.get(Thread, 210)
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
        move_to_position(thread.id, user.id, new_position, db)

        # Refresh and verify
        db.refresh(thread)

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
            db.commit()
            print("✅ SUCCESS: Reorder event created")

        else:
            print(
                f"❌ FAILURE: Thread position is {thread.queue_position}, expected {new_position}"
            )

    except Exception as e:
        print(f"❌ ERROR: {e}")
        db.rollback()
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    test_thread_reposition()
