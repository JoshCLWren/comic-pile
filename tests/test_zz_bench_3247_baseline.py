"""TEMPORARY baseline benchmark for issue #3247 (deleted after evidence capture)."""

import statistics
import time

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.comicvine_hydration import normalize_issue
from app.models import Event, Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

TARGET_CREATOR = 42389
THREADS = 100
ISSUES_PER_THREAD = 60

_serial = 0


def _provider_issue_result(issue_number: int, person_ids: list[int]) -> dict[str, object]:
    return {
        "id": 900_000 + issue_number,
        "name": f"Bench Issue {issue_number}",
        "issue_number": str(issue_number),
        "cover_date": "2026-01-01",
        "site_detail_url": "https://comicvine.gamespot.com/issue/4000-900000/",
        "image": {
            "original_url": "https://example.invalid/original.jpg",
            "super_url": "https://example.invalid/super.jpg",
            "medium_url": "https://example.invalid/medium.jpg",
            "small_url": "https://example.invalid/small.jpg",
        },
        "volume": {
            "id": 5_000,
            "name": "Bench Volume",
            "api_detail_url": "https://comicvine.gamespot.com/api/volume/4050-5000/",
            "site_detail_url": "https://comicvine.gamespot.com/volume/4000-5000/",
        },
        "person_credits": [
            {
                "id": person_id,
                "name": f"Creator {person_id}",
                "api_detail_url": f"https://comicvine.gamespot.com/api/person/1-{person_id}/",
                "site_detail_url": f"https://comicvine.gamespot.com/person/4000-{person_id}/",
                "role": role,
            }
            for person_id, role in zip(
                person_ids, ("writer", "penciler", "inker", "cover"), strict=False
            )
        ],
        "character_credits": [
            {
                "id": 9_000 + offset,
                "name": f"Character {offset}",
                "api_detail_url": "https://comicvine.gamespot.com/api/character/4005-9000/",
                "site_detail_url": "https://comicvine.gamespot.com/character/4000-9000/",
            }
            for offset in range(24)
        ],
        "story_arc_credits": [
            {
                "id": 700 + offset,
                "name": f"Arc {offset}",
                "api_detail_url": "https://comicvine.gamespot.com/api/story_arc/4045-700/",
                "site_detail_url": "https://comicvine.gamespot.com/story-arc/4000-700/",
            }
            for offset in range(8)
        ],
    }


async def _seed_library(db: AsyncSession, user: User) -> int:
    """Seed a production-shaped library and return the target creator's issue count."""
    global _serial
    target_issues = 0
    for thread_index in range(1, THREADS + 1):
        thread = Thread(
            user_id=user.id,
            title=f"Bench Series {thread_index:03d}",
            format="Comic",
            issues_remaining=ISSUES_PER_THREAD,
            total_issues=ISSUES_PER_THREAD,
            queue_position=thread_index,
            status="active",
        )
        db.add(thread)
        await db.flush()
        for position in range(1, ISSUES_PER_THREAD + 1):
            global_index = (thread_index - 1) * ISSUES_PER_THREAD + position
            is_target = global_index % 4 == 0
            others = [500 + (global_index * 7 + offset) % 4000 for offset in range(3)]
            person_ids = ([TARGET_CREATOR] if is_target else []) + others
            status = "read" if global_index % 4 != 3 else "unread"
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(position),
                position=position,
                status=status,
            )
            db.add(issue)
            await db.flush()

            if is_target:
                target_issues += 1

            _serial += 1
            metadata = normalize_issue(
                _provider_issue_result(_serial, person_ids + [800 + (global_index % 5)])
            )
            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=f"bench-{_serial}",
                metadata_json=metadata,
            )
            db.add(identity)
            await db.flush()
            db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                    confidence=1.0,
                )
            )

            if status == "read":
                for version in range(1 + global_index % 3):
                    db.add(
                        Event(
                            type="rate",
                            thread_id=thread.id,
                            issue_id=issue.id,
                            issue_number=issue.issue_number,
                            rating=float(1 + (global_index + version) % 5),
                            timestamp=__import__("datetime").datetime(
                                2026, 3, 1 + version, tzinfo=__import__("datetime").UTC
                            ),
                        )
                    )
    await db.flush()
    return target_issues


class _QueryTimer:
    def __init__(self, engine: AsyncEngine) -> None:
        self.selects = 0
        self.db_ms = 0.0
        self.per_query: list[tuple[float, str]] = []
        self._engine = engine

    def __enter__(self) -> _QueryTimer:
        self._before = event.contains(self._engine.sync_engine, "before_cursor_execute", self._pre)

        event.listen(self._engine.sync_engine, "before_cursor_execute", self._pre)
        event.listen(self._engine.sync_engine, "after_cursor_execute", self._post)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(self._engine.sync_engine, "before_cursor_execute", self._pre)
        event.remove(self._engine.sync_engine, "after_cursor_execute", self._post)

    def _pre(self, conn: object, cursor: object, statement: str, parameters: object,
             context: object, executemany: bool) -> None:
        self._start = time.perf_counter()

    def _post(self, conn: object, cursor: object, statement: str, parameters: object,
              context: object, executemany: bool) -> None:
        elapsed = (time.perf_counter() - self._start) * 1000
        self.db_ms += elapsed
        if statement.lstrip().upper().startswith("SELECT"):
            self.selects += 1
            self.per_query.append((elapsed, " ".join(statement.split())[:160]))


@pytest.mark.asyncio
async def test_baseline_creator_detail_benchmark(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """TEMPORARY baseline benchmark for issue #3247 (deleted after evidence capture)."""
    seeded = await _seed_library(async_db, default_user)
    total_issues = await async_db.scalar(text("SELECT COUNT(*) FROM issues"))
    print(f"\nSeeded: {total_issues} issues, target creator on {seeded}")

    key = f"creator:{TARGET_CREATOR}"
    # Warm-up (pool, statement caches, page cache).
    for _ in range(2):
        warm = await auth_client.get(f"/api/v1/creators/{key}")
        assert warm.status_code == 200

    wall_times: list[float] = []
    query_counts: list[int] = []
    db_times: list[float] = []
    payload_bytes = 0
    with _QueryTimer(db_engine) as timer:
        for _ in range(5):
            start = time.perf_counter()
            response = await auth_client.get(f"/api/v1/creators/{key}")
            wall_times.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200
            payload_bytes = len(response.content)
            query_counts.append(timer.selects)
            db_times.append(timer.db_ms)
            timer.selects = 0
            timer.db_ms = 0.0

    print(f"Payload: {payload_bytes} bytes")
    print(f"Warm wall ms: {[round(w, 1) for w in wall_times]}")
    print(f"median={statistics.median(wall_times):.1f}ms min={min(wall_times):.1f}ms")
    print(f"SELECT count per request: {query_counts}")
    print(f"DB ms per request: {[round(d, 1) for d in db_times]}")

    # Also measure the summaries endpoint for context.
    with _QueryTimer(db_engine) as timer2:
        start = time.perf_counter()
        resp2 = await auth_client.get(f"/api/v1/creators/summaries?keys={key}")
        summaries_ms = (time.perf_counter() - start) * 1000
    print(f"summaries endpoint: {summaries_ms:.1f}ms, selects={timer2.selects}, status={resp2.status_code}")

    # Per-query breakdown for one more detail read.
    timer.selects = 0
    timer.db_ms = 0.0
    timer.per_query = []
    with _QueryTimer(db_engine) as timer3:
        resp3 = await auth_client.get(f"/api/v1/creators/{key}")
        assert resp3.status_code == 200
    for elapsed, snippet in timer3.per_query:
        print(f"  {elapsed:8.1f}ms  {snippet}")
