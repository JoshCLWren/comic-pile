#!/usr/bin/env python3
"""Update issue number for Miles Morales: Spider-Man from #1 to #42."""

import asyncio
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Issue


async def update_issue_number() -> None:
    """Update Miles Morales: Spider-Man issue from #1 to #42."""
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Issue).where(Issue.id == 10471))
            issue = result.scalar_one_or_none()

            if issue:
                print(f"Found issue: {issue.id} - #{issue.issue_number}")
                issue.issue_number = "42"
                await db.commit()
                print("✅ Updated issue_number to '42'")
            else:
                print("❌ Issue not found")

        except Exception as e:
            await db.rollback()
            print(f"❌ Error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(update_issue_number())
