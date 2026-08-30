#!/usr/bin/env python3
"""Add missing issues #21-24 to The Ultimates thread."""

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Issue, Thread


async def add_ultimates_issues() -> None:
    """Add issues #21-24 to The Ultimates thread."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Thread).where(Thread.id == 321))
            thread = result.scalar_one_or_none()

            if not thread:
                print("❌ Thread not found")
                return

            print(f"Found thread: {thread.title}")
            print(f"Current total_issues: {thread.total_issues}")

            if thread.total_issues is None:
                print("❌ Thread not migrated to issue tracking")
                return

            # Get the highest current position
            result = await db.execute(
                select(Issue)
                .where(Issue.thread_id == thread.id)
                .order_by(Issue.position.desc())
                .limit(1)
            )
            last_issue = result.scalar_one_or_none()

            if not last_issue:
                print("❌ No issues found")
                return

            last_position = last_issue.position
            print(f"Last issue position: {last_position}")

            # Add issues #21-24
            for i in range(21, 25):
                issue = Issue(
                    thread_id=thread.id,
                    issue_number=str(i),
                    status="unread",
                    read_at=None,
                    position=i,
                )
                db.add(issue)
                print(f"  Adding issue #{i}")

            await db.flush()

            # Update total_issues
            thread.total_issues = 24

            await db.commit()
            print("✅ Added issues #21-24")

        except Exception as e:
            await db.rollback()
            print(f"❌ Error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(add_ultimates_issues())
