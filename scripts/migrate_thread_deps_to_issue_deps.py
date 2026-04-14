#!/usr/bin/env python3
"""Migrate thread-level dependencies to issue-level equivalents.

One-time data migration for issue #412.  Finds every Dependency row where
source_thread_id IS NOT NULL, resolves the last issue of the source thread
and the first issue of the target thread, creates an equivalent issue-level
dependency, then deletes the original thread-level row.

Run this script BEFORE applying the Alembic migration that drops the
source_thread_id / target_thread_id columns.

Usage:
    python -m scripts.migrate_thread_deps_to_issue_deps
"""

import asyncio
import os
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import Dependency, Issue, Thread
from comic_pile.dependencies import refresh_user_blocked_status

# Ensure project root is importable when executed directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def _last_issue_of_thread(thread_id: int, db: AsyncSession) -> Issue | None:
    """Return the issue with the highest position in the given thread."""
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def _first_issue_of_thread(thread_id: int, db: AsyncSession) -> Issue | None:
    """Return the issue with the lowest position in the given thread."""
    result = await db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position.asc()).limit(1)
    )
    return result.scalar_one_or_none()


async def migrate_thread_deps_to_issue_deps() -> None:
    """Migrate all thread-level dependencies to issue-level equivalents.

    Uses raw SQL to read the legacy source_thread_id / target_thread_id columns
    so this script works even after those columns have been removed from the ORM
    model (provided they still exist in the database schema at run time).
    """
    async with AsyncSessionLocal() as db:
        # Use raw SQL to access the legacy columns regardless of ORM model state.
        raw = await db.execute(
            text(
                "SELECT id, source_thread_id, target_thread_id, note "
                "FROM dependencies "
                "WHERE source_thread_id IS NOT NULL"
            )
        )
        thread_dep_rows = raw.fetchall()

        if not thread_dep_rows:
            print("No thread-level dependencies found. Nothing to migrate.")
            return

        print(f"Found {len(thread_dep_rows)} thread-level dependencies to migrate.\n")

        affected_user_ids: set[int] = set()
        migrated = 0
        skipped = 0

        for row in thread_dep_rows:
            dep_id: int = row[0]
            source_thread_id: int = row[1]
            target_thread_id: int = row[2]
            dep_note: str | None = row[3]

            source_issue = await _last_issue_of_thread(source_thread_id, db)
            target_issue = await _first_issue_of_thread(target_thread_id, db)

            if not source_issue or not target_issue:
                source_thread = await db.get(Thread, source_thread_id)
                target_thread = await db.get(Thread, target_thread_id)
                source_title = source_thread.title if source_thread else "unknown"
                target_title = target_thread.title if target_thread else "unknown"
                print(
                    f"  SKIP dep #{dep_id}: {source_title} -> {target_title} "
                    "(one or both threads have no issues)"
                )
                skipped += 1
                continue

            existing = await db.execute(
                select(Dependency).where(
                    Dependency.source_issue_id == source_issue.id,
                    Dependency.target_issue_id == target_issue.id,
                )
            )
            if existing.scalar_one_or_none():
                print(
                    f"  SKIP dep #{dep_id}: issue-level equivalent already exists "
                    f"(issue #{source_issue.issue_number} -> issue #{target_issue.issue_number})"
                )
                await db.execute(text("DELETE FROM dependencies WHERE id = :id"), {"id": dep_id})
                skipped += 1
                continue

            source_thread = await db.get(Thread, source_thread_id)
            target_thread = await db.get(Thread, target_thread_id)
            source_title = source_thread.title if source_thread else "unknown"
            target_title = target_thread.title if target_thread else "unknown"

            print(
                f"  MIGRATE dep #{dep_id}: {source_title} -> {target_title} "
                f"(issue #{source_issue.issue_number} -> issue #{target_issue.issue_number})"
            )

            new_dep = Dependency(
                source_issue_id=source_issue.id,
                target_issue_id=target_issue.id,
                note=dep_note,
            )
            db.add(new_dep)
            await db.execute(text("DELETE FROM dependencies WHERE id = :id"), {"id": dep_id})

            if source_thread and source_thread.user_id:
                affected_user_ids.add(source_thread.user_id)
            if target_thread and target_thread.user_id:
                affected_user_ids.add(target_thread.user_id)

            migrated += 1

        if migrated == 0 and skipped == 0:
            print("Nothing to do.")
            return

        await db.flush()

        for user_id in affected_user_ids:
            await refresh_user_blocked_status(user_id, db)

        await db.commit()

        print(f"\nMigration complete: {migrated} migrated, {skipped} skipped.")


if __name__ == "__main__":
    asyncio.run(migrate_thread_deps_to_issue_deps())
