#!/usr/bin/env python
"""Clean up test users from the database.

This script deletes all users whose usernames match the test patterns
(auth_test_*, testuser_*, testuser) and all their associated data.
"""

import asyncio
import os
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Event, Session, Snapshot, Thread
from app.models.user import User

ASYNC_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://comicpile:comicpile_password@localhost:5435/comicpile"
    ),
)


async def cleanup_test_users():
    """Delete all test users and their associated data."""
    engine = create_async_engine(ASYNC_DB_URL)
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with async_session_maker() as session:
        # Find all test users
        result = await session.execute(
            select(User).where(
                (User.username.like("auth_test_%"))
                | (User.username.like("testuser_%"))
                | (User.username.like("test_%"))
            )
        )
        test_users = result.scalars().all()

        print(f"Found {len(test_users)} test users to delete")

        deleted_threads = 0
        deleted_sessions = 0
        deleted_events = 0
        deleted_snapshots = 0

        for user in test_users:
            user_id = user.id
            print(f"Deleting user: {user.username} (ID: {user_id})")

            # Get all threads for this user
            thread_result = await session.execute(select(Thread).where(Thread.user_id == user_id))
            threads = thread_result.scalars().all()
            thread_ids = [t.id for t in threads]

            # Delete events associated with these threads
            for thread_id in thread_ids:
                events_result = await session.execute(
                    select(Event).where(
                        (Event.thread_id == thread_id) | (Event.selected_thread_id == thread_id)
                    )
                )
                events = events_result.scalars().all()
                for event in events:
                    await session.delete(event)
                deleted_events += len(events)

            # Delete snapshots associated with this user's sessions
            sessions_result = await session.execute(
                select(Session).where(Session.user_id == user_id)
            )
            sessions = sessions_result.scalars().all()
            session_ids = [s.id for s in sessions]

            for session_id in session_ids:
                snapshot_result = await session.execute(
                    select(Snapshot).where(Snapshot.session_id == session_id)
                )
                snapshots = snapshot_result.scalars().all()
                for snapshot in snapshots:
                    await session.delete(snapshot)
                deleted_snapshots += len(snapshots)

            # Delete sessions
            deleted_sessions += len(sessions)
            for session_obj in sessions:
                await session.delete(session_obj)

            # Delete threads
            deleted_threads += len(threads)
            for thread in threads:
                await session.delete(thread)

            # Delete user
            await session.delete(user)

        await session.commit()

        print("\nCleanup complete:")
        print(f"  Deleted {deleted_threads} threads")
        print(f"  Deleted {deleted_sessions} sessions")
        print(f"  Deleted {deleted_events} events")
        print(f"  Deleted {deleted_snapshots} snapshots")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(cleanup_test_users())
