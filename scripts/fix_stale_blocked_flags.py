#!/usr/bin/env python3
"""Recalculate stale is_blocked flags for all users.

One-time fix after the dependency blocking logic change (PR #299).  The fix
narrowed get_blocked_thread_ids to only look at each thread's next_unread_issue_id
instead of all issues, but the denormalized is_blocked column on Thread was never
recalculated for existing rows.  Run this once against production after deploy.

Usage:
    python -m scripts.fix_stale_blocked_flags
"""

import asyncio

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import Thread, User
from comic_pile.dependencies import refresh_user_blocked_status


async def fix_stale_blocked_flags() -> None:
    """Recalculate is_blocked for every user and report changes."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id, User.username))
        users = result.all()

        if not users:
            print("No users found.")
            return

        print(f"Refreshing blocked status for {len(users)} user(s)...\n")

        for user_id, username in users:
            before_result = await db.execute(
                select(Thread.id, Thread.title)
                .where(Thread.user_id == user_id)
                .where(Thread.is_blocked.is_(True))
                .where(Thread.status == "active")
            )
            blocked_before = {row[0]: row[1] for row in before_result.all()}

            await refresh_user_blocked_status(user_id, db)

            after_result = await db.execute(
                select(Thread.id, Thread.title)
                .where(Thread.user_id == user_id)
                .where(Thread.is_blocked.is_(True))
                .where(Thread.status == "active")
            )
            blocked_after = {row[0]: row[1] for row in after_result.all()}

            unblocked = {tid: blocked_before[tid] for tid in blocked_before if tid not in blocked_after}
            newly_blocked = {tid: blocked_after[tid] for tid in blocked_after if tid not in blocked_before}

            print(f"User '{username}' (id={user_id}):")
            print(f"  Blocked before: {len(blocked_before)}  After: {len(blocked_after)}")
            if unblocked:
                for tid, title in unblocked.items():
                    print(f"  ✓ Unblocked: [{tid}] {title}")
            if newly_blocked:
                for tid, title in newly_blocked.items():
                    print(f"  ✗ Newly blocked: [{tid}] {title}")
            if not unblocked and not newly_blocked:
                print("  No changes.")
            print()

        await db.commit()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(fix_stale_blocked_flags())
