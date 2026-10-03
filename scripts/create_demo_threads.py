"""Script to create demo threads for guest demo feature.

This script creates sample threads that can be used by guest users
to experience the ComicPile roll functionality without creating an account.
"""

import asyncio
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_database_url
from app.models.thread import Thread

# Sample demo data
DEMO_THREADS = [
    {
        "title": "Spider-Man: Amazing Fantasy",
        "format": "Comic",
        "total_issues": 15,
        "issues_remaining": 15,
        "queue_position": 1,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Batman: The Dark Knight Returns",
        "format": "Comic",
        "total_issues": 4,
        "issues_remaining": 4,
        "queue_position": 2,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "X-Men: Days of Future Past",
        "format": "Comic",
        "total_issues": 6,
        "issues_remaining": 6,
        "queue_position": 3,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Wonder Woman: Paradise Island",
        "format": "Comic",
        "total_issues": 12,
        "issues_remaining": 12,
        "queue_position": 4,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "The Flash: Born to Run",
        "format": "Comic",
        "total_issues": 9,
        "issues_remaining": 9,
        "queue_position": 5,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Green Lantern: Emerald Twilight",
        "format": "Comic",
        "total_issues": 8,
        "issues_remaining": 8,
        "queue_position": 6,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Captain America: Winter Soldier",
        "format": "Comic",
        "total_issues": 5,
        "issues_remaining": 5,
        "queue_position": 7,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Iron Man: Extremis",
        "format": "Comic",
        "total_issues": 6,
        "issues_remaining": 6,
        "queue_position": 8,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "Thor: God of Thunder",
        "format": "Comic",
        "total_issues": 11,
        "issues_remaining": 11,
        "queue_position": 9,
        "status": "active",
        "is_demo_thread": True,
    },
    {
        "title": "The Incredible Hulk: Planet Hulk",
        "format": "Comic",
        "total_issues": 12,
        "issues_remaining": 12,
        "queue_position": 10,
        "status": "active",
        "is_demo_thread": True,
    },
]


async def create_demo_threads() -> None:
    """Create demo threads in the database."""
    # Use the database URL from config
    database_url = get_database_url()
    
    # Create async engine
    engine = create_async_engine(database_url)
    
    # Create sessionmaker
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    
    async with async_session() as session:
        try:
            # Check if demo threads already exist
            result = await session.execute(
                sa.select(Thread).where(Thread.is_demo_thread)
            )
            existing_demo_threads = result.scalars().all()
            
            if existing_demo_threads:
                print(f"Found {len(existing_demo_threads)} existing demo threads. Skipping creation.")
                return
            
            # Create demo threads
            print("Creating demo threads...")
            for demo_thread_data in DEMO_THREADS:
                demo_thread = Thread(
                    user_id=1,  # Assign to a default user (could be a demo user)
                    created_at=datetime.now(UTC),
                    **demo_thread_data
                )
                session.add(demo_thread)
            
            await session.commit()
            print(f"Successfully created {len(DEMO_THREADS)} demo threads.")
            
        except Exception as e:
            print(f"Error creating demo threads: {e}")
            await session.rollback()
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_demo_threads())