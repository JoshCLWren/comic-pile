#!/usr/bin/env python3
"""Audit script for thread positions and queue consistency.

This script checks for:
- Thread 210 details (owner, current position, status)
- All threads for testuser123 with their positions
- Gaps or inconsistencies in position numbering
- Active vs total thread counts
- Sequential position verification
"""

import asyncio
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select, func

from app.database import AsyncSessionLocal
from app.models import Thread, User


class ThreadAuditResult(NamedTuple):
    """Results of thread audit."""

    thread_id: int
    title: str
    username: str
    user_id: int
    queue_position: int
    status: str
    is_test: bool
    issues_remaining: int
    last_rating: float | None
    created_at: datetime


class PositionGap(NamedTuple):
    """Represents a gap in queue positions."""

    expected_position: int
    actual_positions: list[int]


async def get_thread_210_details(db) -> ThreadAuditResult | None:
    """Get detailed information about thread 210."""
    result = await db.execute(select(Thread).where(Thread.id == 210))
    thread = result.scalar_one_or_none()

    if not thread:
        return None

    result = await db.execute(select(User).where(User.id == thread.user_id))
    user = result.scalar_one()

    return ThreadAuditResult(
        thread_id=thread.id,
        title=thread.title,
        username=user.username,
        user_id=thread.user_id,
        queue_position=thread.queue_position,
        status=thread.status,
        is_test=thread.is_test,
        issues_remaining=thread.issues_remaining,
        last_rating=thread.last_rating,
        created_at=thread.created_at,
    )


async def get_testuser123_threads(db) -> list[ThreadAuditResult]:
    """Get all threads for testuser123 with their details."""
    result = await db.execute(select(User).where(User.username == "testuser123"))
    testuser = result.scalar_one_or_none()

    if not testuser:
        return []

    result = await db.execute(
        select(Thread).where(Thread.user_id == testuser.id).order_by(Thread.queue_position)
    )
    threads = result.scalars().all()

    return [
        ThreadAuditResult(
            thread_id=thread.id,
            title=thread.title,
            username=testuser.username,
            user_id=thread.user_id,
            queue_position=thread.queue_position,
            status=thread.status,
            is_test=thread.is_test,
            issues_remaining=thread.issues_remaining,
            last_rating=thread.last_rating,
            created_at=thread.created_at,
        )
        for thread in threads
    ]


async def check_position_gaps(db) -> list[PositionGap]:
    """Check for gaps in queue positions across all threads."""
    result = await db.execute(
        select(Thread.queue_position)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    all_positions = result.scalars().all()

    if not all_positions:
        return []

    gaps = []
    expected_position = 1

    for actual_position in all_positions:
        if actual_position < expected_position:
            continue
        while actual_position > expected_position:
            gaps.append(PositionGap(expected_position, []))
            expected_position += 1
        expected_position += 1

    return gaps


async def get_thread_statistics(db) -> dict[str, int | dict[str, int]]:
    """Get overall thread statistics."""
    stats = {}

    # Total threads
    result = await db.execute(select(func.count(Thread.id)))
    stats["total_threads"] = result.scalar()

    # Active threads
    result = await db.execute(select(func.count(Thread.id)).where(Thread.status == "active"))
    stats["active_threads"] = result.scalar()

    # Test threads
    result = await db.execute(select(func.count(Thread.id)).where(Thread.is_test))
    stats["test_threads"] = result.scalar()

    # Production threads
    stats["production_threads"] = (stats["total_threads"] or 0) - (stats["test_threads"] or 0)

    # Threads by user
    result = await db.execute(
        select(User.username, func.count(Thread.id))
        .join(Thread)
        .group_by(User.username)
        .order_by(func.count(Thread.id).desc())
    )
    user_thread_counts = result.all()

    stats["threads_by_user"] = {row[0]: row[1] for row in user_thread_counts}

    return stats


async def check_position_duplicates(db) -> dict[int, list[int]]:
    """Check for duplicate queue positions."""
    duplicates = {}

    result = await db.execute(
        select(Thread.queue_position, func.count(Thread.id))
        .where(Thread.status == "active")
        .group_by(Thread.queue_position)
        .having(func.count(Thread.id) > 1)
    )
    positions_with_counts = result.all()

    for position, _count in positions_with_counts:
        result = await db.execute(
            select(Thread.id).where(Thread.queue_position == position, Thread.status == "active")
        )
        thread_ids = result.scalars().all()
        duplicates[position] = thread_ids

    return duplicates


def print_thread_details(thread: ThreadAuditResult, title_prefix: str = "") -> None:
    """Print formatted thread details."""
    print(f"{title_prefix}Thread ID: {thread.thread_id}")
    print(f"  Title: {thread.title}")
    print(f"  Owner: {thread.username} (ID: {thread.user_id})")
    print(f"  Position: {thread.queue_position}")
    print(f"  Status: {thread.status}")
    print(f"  Test: {thread.is_test}")
    print(f"  Issues Remaining: {thread.issues_remaining}")
    print(f"  Last Rating: {thread.last_rating}")
    print(f"  Created: {thread.created_at}")
    print()


async def main() -> None:
    """Run the thread audit."""
    print("=== Thread Queue Audit ===")
    print(f"Audit started at: {datetime.now()}")
    print()

    async with AsyncSessionLocal() as db:
        try:
            # 1. Thread 210 details
            print("1. THREAD 210 DETAILS")
            print("-" * 30)
            thread_210 = await get_thread_210_details(db)
            if thread_210:
                print_thread_details(thread_210, "✓ ")
            else:
                print("✗ Thread 210 not found")
            print()

            # 2. testuser123 threads
            print("2. TESTUSER123 THREADS")
            print("-" * 30)
            testuser_threads = await get_testuser123_threads(db)
            if testuser_threads:
                print(f"✓ Found {len(testuser_threads)} threads for testuser123:")
                print()
                for thread in testuser_threads:
                    print_thread_details(thread)
            else:
                print("✗ No threads found for testuser123 (user may not exist)")
            print()

            # 3. Position gaps
            print("3. POSITION GAP ANALYSIS")
            print("-" * 30)
            gaps = await check_position_gaps(db)
            if gaps:
                print(f"✗ Found {len(gaps)} gaps in position numbering:")
                for gap in gaps:
                    print(f"  Missing position: {gap.expected_position}")
            else:
                print("✓ No gaps found in active thread positions")
            print()

            # 4. Position duplicates
            print("4. POSITION DUPLICATE ANALYSIS")
            print("-" * 30)
            duplicates = await check_position_duplicates(db)
            if duplicates:
                print(f"✗ Found {len(duplicates)} positions with duplicates:")
                for position, thread_ids in duplicates.items():
                    print(f"  Position {position}: Threads {thread_ids}")
            else:
                print("✓ No duplicate positions found")
            print()

            # 5. Thread statistics
            print("5. THREAD STATISTICS")
            print("-" * 30)
            stats = await get_thread_statistics(db)
            print(f"Total threads: {stats['total_threads']}")
            print(f"Active threads: {stats['active_threads']}")
            print(f"Test threads: {stats['test_threads']}")
            print(f"Production threads: {stats['production_threads']}")
            print()
            print("Threads by user:")
            threads_by_user = stats.get("threads_by_user")
            if isinstance(threads_by_user, dict):
                for username, count in threads_by_user.items():
                    print(f"  {username}: {count}")
            print()

            # 6. Position sequence validation
            print("6. POSITION SEQUENCE VALIDATION")
            print("-" * 30)
            result = await db.execute(
                select(Thread).where(Thread.status == "active").order_by(Thread.queue_position)
            )
            active_threads = result.scalars().all()

            if active_threads:
                expected_position = 1
                issues_found = []

                for thread in active_threads:
                    if thread.queue_position != expected_position:
                        issues_found.append(
                            f"Thread {thread.id} at position {thread.queue_position} "
                            f"(expected {expected_position})"
                        )
                    expected_position += 1

                if issues_found:
                    print("✗ Position sequence issues found:")
                    for issue in issues_found:
                        print(f"  {issue}")
                else:
                    print("✓ All active threads are in correct sequential positions")
            else:
                print("✗ No active threads found")
            print()

            # 7. Summary and recommendations
            print("7. AUDIT SUMMARY")
            print("-" * 30)

            issues = []
            if not thread_210:
                issues.append("Thread 210 not found")
            if gaps:
                issues.append(f"{len(gaps)} position gaps found")
            if duplicates:
                issues.append(f"{len(duplicates)} position duplicates found")

            if issues:
                print("✗ Issues found that need attention:")
                for issue in issues:
                    print(f"  - {issue}")
                print()
                print("Recommendations:")
                if thread_210 and thread_210.queue_position > 11:
                    print("  - Thread 210 is at position > 11, move should be possible")
                elif thread_210:
                    print(
                        "  - Thread 210 is at or before position 11, check target position availability"
                    )
                if gaps:
                    print("  - Reorganize positions to eliminate gaps")
                if duplicates:
                    print("  - Resolve duplicate positions before moving threads")
            else:
                print("✓ No issues found - queue consistency is good")
                if thread_210:
                    print(f"✓ Thread 210 is at position {thread_210.queue_position}")
                    if thread_210.queue_position > 11:
                        print("✓ Moving to position 11 should be possible")
                    else:
                        print("✗ Moving to position 11 may conflict with existing thread")

        except Exception as e:
            print(f"✗ Audit failed with error: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())
