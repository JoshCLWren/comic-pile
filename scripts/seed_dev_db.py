#!/usr/bin/env python3
"""Seed dev database with test user and threads."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.auth import hash_password
from app.config import get_database_settings
from app.database import AsyncSessionLocal
from app.models import Session as SessionModel, Thread, User


async def seed_database():
    """Create test user with sample threads and session."""
    settings = get_database_settings()

    db_url = settings.database_url
    if "@" in db_url:
        print(f"Seeding database: {db_url.split('@')[1]}")
    else:
        print(f"Seeding database: {db_url}")

    async with AsyncSessionLocal() as db:
        # Check if test user exists
        result = await db.execute(select(User).where(User.email == "test@example.com"))
        user = result.scalar_one_or_none()

        if user:
            print(f"Test user already exists (ID: {user.id})")
            # Delete existing threads and sessions
            threads_result = await db.execute(select(Thread).where(Thread.user_id == user.id))
            for thread in threads_result.scalars().all():
                await db.delete(thread)

            sessions_result = await db.execute(
                select(SessionModel).where(SessionModel.user_id == user.id)
            )
            for session in sessions_result.scalars().all():
                await db.delete(session)

            await db.commit()
            print("Cleared existing threads and sessions")
        else:
            # Create new test user
            user = User(
                username="test@example.com",
                email="test@example.com",
                password_hash=hash_password("testpass123"),
                is_admin=False,
                created_at=datetime.now(UTC),
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Created test user (ID: {user.id})")

        # Create sample threads
        threads = [
            Thread(
                title="Superman",
                format="Comic",
                issues_remaining=10,
                queue_position=1,
                status="active",
                user_id=user.id,
                created_at=datetime.now(UTC),
            ),
            Thread(
                title="Batman",
                format="Comic",
                issues_remaining=5,
                queue_position=2,
                status="active",
                user_id=user.id,
                created_at=datetime.now(UTC),
            ),
            Thread(
                title="Wonder Woman",
                format="Comic",
                issues_remaining=0,
                queue_position=3,
                status="completed",
                user_id=user.id,
                created_at=datetime.now(UTC),
            ),
            Thread(
                title="The Flash",
                format="Comic",
                issues_remaining=8,
                queue_position=4,
                status="active",
                user_id=user.id,
                created_at=datetime.now(UTC),
            ),
            Thread(
                title="Aquaman",
                format="Comic",
                issues_remaining=3,
                queue_position=5,
                status="active",
                user_id=user.id,
                created_at=datetime.now(UTC),
            ),
        ]

        for thread in threads:
            db.add(thread)
        await db.commit()
        print(f"Created {len(threads)} threads")

        # Create active session
        session = SessionModel(
            start_die=6,
            user_id=user.id,
            started_at=datetime.now(UTC),
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        print(f"Created active session (ID: {session.id}, start_die: {session.start_die})")

        print("\nDatabase seeded successfully!")
        print("Email: test@example.com")
        print("Password: testpass123")
        print("\nThreads created:")
        for thread in threads:
            print(
                f"  - {thread.title} (#{thread.queue_position}, {thread.issues_remaining} issues remaining, {thread.status})"
            )


if __name__ == "__main__":
    asyncio.run(seed_database())
