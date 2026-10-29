#!/usr/bin/env python3
"""Add a reproducible, production-shaped *synthetic* fixture to a disposable local DB.

Does not access Neon, copy personal records, or clear existing data.
Run as a module: uv run python -m scripts.seed_profile_fixture --db-url ...
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
import os
import random

from urllib import parse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from scripts.profile_local_traffic import safe_database_url

PREFIX = "CPU Profile Series "
LIST_PREFIX = "CPU Profile Reading List "
RANDOM_SEED = 4277


def async_database_url(value: str) -> str:
    """Convert any accepted local PostgreSQL URL to the asyncpg driver.

    ``safe_database_url`` accepts plain ``postgres://`` and ``postgresql://``
    schemes for compatibility with common local connection strings, but
    SQLAlchemy's async engine requires the ``postgresql+asyncpg://`` driver
    scheme, matching ``DatabaseSettings.async_url``.
    """
    parsed = safe_database_url(value)
    if parsed.scheme == "postgresql+asyncpg":
        return value
    return parse.urlunsplit(parsed._replace(scheme="postgresql+asyncpg"))


async def seed(
    db_url: str,
    username: str,
    *,
    series_count: int = 315,
    issues_per_series: int = 24,
    history_sessions: int = 79,
    lists: int = 12,
) -> dict[str, int]:
    """Append deterministic synthetic history and continuity data atomically."""
    parsed = safe_database_url(db_url)
    # A loopback address alone is not proof that the DB is disposable.
    if "profile" not in parsed.path.lower():
        raise ValueError("Database name must contain 'profile' for fixture writes")
    if series_count < 20 or series_count > 1000:
        raise ValueError("series_count must be 20..1000")
    if issues_per_series < 4 or issues_per_series > 80:
        raise ValueError("issues_per_series must be 4..80")
    if history_sessions < 0 or history_sessions > 1000:
        raise ValueError("history_sessions must be 0..1000")
    if lists < 0 or lists > 40:
        raise ValueError("lists must be 0..40")

    # Import AFTER validating target. The app's global DB engine is not used.
    from app.models import (
        CustomCBLEntry,
        CustomCBLList,
        Dependency,
        Event,
        Issue,
        ReadingOrder,
        ReadingOrderItem,
        ReadingSession,
        Thread,
        User,
    )

    rnd = random.Random(RANDOM_SEED)
    engine = create_async_engine(async_database_url(db_url), pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db, db.begin():
            user = await db.scalar(select(User).where(User.username == username))
            if user is None or user.password_hash is None:
                raise ValueError(f"No password-backed local user {username!r}; seed the test account first")
            already_seeded = await db.scalar(
                select(Thread.id).where(
                    Thread.user_id == user.id, Thread.title.like(PREFIX + "%")
                ).limit(1)
            )
            if already_seeded is not None:
                raise ValueError("Synthetic profile fixture already present; refusing to duplicate it")

            highest = await db.scalars(
                select(Thread.queue_position).where(Thread.user_id == user.id)
            )
            next_queue_pos = max(highest.all(), default=0) + 1
            now = datetime.now(UTC)
            thread_objects: list[Thread] = []
            first_unread: dict[int, Issue] = {}
            issues_by_thread: dict[int, list[Issue]] = {}
            for n in range(series_count):
                # Mostly active reading, a smaller completed/snoozed-style tail.
                completed = n % 9 == 0
                read_count = issues_per_series if completed else n % (issues_per_series - 1)
                unread = issues_per_series - read_count
                thread = Thread(
                    title=f"{PREFIX}{n + 1:04d}",
                    format="Comic",
                    user_id=user.id,
                    queue_position=next_queue_pos + n,
                    status="completed" if completed else "active",
                    issues_remaining=unread,
                    total_issues=issues_per_series,
                    reading_progress=f"{round(read_count * 100 / issues_per_series)}%",
                    last_rating=round(1 + 4 * rnd.random(), 1) if n % 5 else None,
                    last_activity_at=now - timedelta(days=n % 90),
                    is_test=True,
                    is_blocked=False,
                )
                thread_objects.append(thread)
            db.add_all(thread_objects)
            await db.flush()

            all_issues: list[Issue] = []
            for n, thread in enumerate(thread_objects):
                completed = n % 9 == 0
                read_count = issues_per_series if completed else n % (issues_per_series - 1)
                bundle: list[Issue] = []
                for position in range(1, issues_per_series + 1):
                    read = position <= read_count
                    issue = Issue(
                        thread_id=thread.id,
                        issue_number=str(position),
                        position=position,
                        status="read" if read else "unread",
                        read_at=(now - timedelta(days=issues_per_series - position + n % 30))
                        if read else None,
                    )
                    bundle.append(issue)
                    all_issues.append(issue)
                issues_by_thread[thread.id] = bundle
                if read_count < issues_per_series:
                    first_unread[thread.id] = bundle[read_count]
            db.add_all(all_issues)
            await db.flush()

            # One deferred-FK-valid frontier per active series.
            for thread in thread_objects:
                frontier = first_unread.get(thread.id)
                if frontier is not None:
                    thread.next_unread_issue_id = frontier.id
            await db.flush()

            # Explicit dependencies are exceptional; the fixture is not trying to
            # reconstruct a real reader's entire Option E continuity contract.
            deps: list[Dependency] = []
            for n in range(2, series_count):
                if n % 3 != 0:
                    continue
                target_thread = thread_objects[n]
                prior_thread = thread_objects[n - 1]
                target = first_unread.get(target_thread.id)
                source = first_unread.get(prior_thread.id)
                if target is None or source is None:
                    continue
                deps.append(
                    Dependency(
                        source_issue_id=source.id,
                        target_issue_id=target.id,
                        origin="reader",
                        note="Synthetic local CPU profiling dependency",
                    )
                )
                target_thread.is_blocked = True
            db.add_all(deps)

            # One existing active reading session is left unchanged. Add ended
            # sessions and historical roll/rate pairs to create realistic joins.
            sessions: list[ReadingSession] = []
            for n in range(history_sessions):
                begin = now - timedelta(days=n + 1, hours=5)
                sessions.append(
                    ReadingSession(
                        user_id=user.id,
                        started_at=begin,
                        ended_at=begin + timedelta(hours=2),
                        start_die=6,
                        manual_die=6 if n % 4 == 0 else None,
                        timezone="America/Chicago",
                    )
                )
            db.add_all(sessions)
            await db.flush()

            events: list[Event] = []
            for n, session in enumerate(sessions):
                for j in range(4):
                    thread = thread_objects[(n * 7 + j * 13) % series_count]
                    issue = issues_by_thread[thread.id][(n + j) % issues_per_series]
                    timestamp = session.started_at + timedelta(minutes=15 + j * 22)
                    events.append(
                        Event(
                            type="roll",
                            session_id=session.id,
                            timestamp=timestamp,
                            die=6,
                            result=(n + j) % 6 + 1,
                            selected_thread_id=thread.id,
                            selection_method="dice",
                            issue_id=issue.id,
                            issue_number=issue.issue_number,
                        )
                    )
                    events.append(
                        Event(
                            type="rate",
                            session_id=session.id,
                            thread_id=thread.id,
                            issue_id=issue.id,
                            issue_number=issue.issue_number,
                            timestamp=timestamp + timedelta(minutes=8),
                            die=6,
                            rating=round(1 + rnd.random() * 4, 1),
                            issues_read=1,
                            die_after=6,
                        )
                    )
            db.add_all(events)

            # Canonical custom reading lists with real issue references.
            cbls: list[CustomCBLList] = []
            for n in range(lists):
                cbls.append(
                    CustomCBLList(
                        user_id=user.id,
                        name=f"{LIST_PREFIX}{n + 1:02d}",
                        mode="strict" if n % 3 == 0 else "loose",
                        description="Synthetic profiling fixture; not a curated reading guide",
                    )
                )
            db.add_all(cbls)
            await db.flush()
            cbl_entries: list[CustomCBLEntry] = []
            legacy_lists: list[ReadingOrder] = []
            for n, cbl in enumerate(cbls):
                # 80 unique canonical issues per list, interleaved across series.
                subset = thread_objects[n * 5 :: 8]
                selected = [issues_by_thread[t.id][(n + k) % issues_per_series]
                            for k, t in enumerate(subset[:80])]
                # Ensure at least a reasonable list length at smaller scales.
                if not selected:
                    selected = [issues_by_thread[thread_objects[n % series_count].id][0]]
                for position, issue in enumerate(selected, start=1):
                    cbl_entries.append(
                        CustomCBLEntry(
                            list_id=cbl.id,
                            issue_id=issue.id,
                            position=position,
                            gate="hold" if position % 9 == 0 else "none",
                            skipped=False,
                        )
                    )
                if n < 5:
                    legacy_lists.append(
                        ReadingOrder(
                            user_id=user.id,
                            name=f"CPU Profile Legacy Order {n + 1:02d}",
                            description="Synthetic profiling fixture",
                        )
                    )
            db.add_all(cbl_entries)
            db.add_all(legacy_lists)
            await db.flush()
            legacy_entries: list[ReadingOrderItem] = []
            for n, reading_order in enumerate(legacy_lists):
                for position, thread in enumerate(thread_objects[n * 5 : n * 5 + 60], start=1):
                    legacy_entries.append(
                        ReadingOrderItem(
                            reading_order_id=reading_order.id,
                            thread_id=thread.id,
                            position=position,
                            issue_number="1",
                        )
                    )
            db.add_all(legacy_entries)
            counts = {
                "added_threads": len(thread_objects),
                "added_issues": len(all_issues),
                "added_dependencies": len(deps),
                "added_historical_sessions": len(sessions),
                "added_events": len(events),
                "added_custom_lists": len(cbls),
                "added_custom_list_entries": len(cbl_entries),
                "added_legacy_orders": len(legacy_lists),
                "added_legacy_order_entries": len(legacy_entries),
            }
        return counts
    finally:
        await engine.dispose()


def main() -> int:
    """Validate local target and add an opt-in repeatable synthetic dataset."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=os.environ.get("LOCAL_PROFILE_DATABASE_URL", ""))
    parser.add_argument("--username", default="testuser")
    parser.add_argument("--series", type=int, default=315)
    parser.add_argument("--issues-per-series", type=int, default=24)
    parser.add_argument("--history-sessions", type=int, default=79)
    parser.add_argument("--lists", type=int, default=12)
    args = parser.parse_args()
    try:
        counts = asyncio.run(
            seed(
                args.db_url,
                args.username,
                series_count=args.series,
                issues_per_series=args.issues_per_series,
                history_sessions=args.history_sessions,
                lists=args.lists,
            )
        )
    except (ValueError, OSError) as exc:
        parser.exit(status=1, message=f"Fixture seed aborted: {exc}\n")
    print("Synthetic fixture committed to the disposable LOCAL database:")
    for key, count in counts.items():
        print(f"  {key}: {count}")
    print("No production data was copied; the existing login and 5 starter threads remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
