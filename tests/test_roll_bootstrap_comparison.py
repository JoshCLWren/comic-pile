"""Production-shaped v1-vs-v2 Roll bootstrap comparison harness (issue #2718).

This is the repeatable proof required before any browser depends on the v2
bootstrap. One fixture library is served through both ``/api/v1/roll/bootstrap``
and ``/api/v2/roll/bootstrap`` on the same database session, and the harness:

* compares every v1-owned semantic (pool membership, ordering, next issue,
  die/pending/last-rolled state, session mode, active thread, recovery,
  snoozed/skipped/blocked/stale summaries, timezone);
* surfaces v1 pool rows with a null issue id and independently proves they hold
  no readable next issue instead of silently normalizing the difference;
* validates v2-only enrichment (canonical series identity, effective ratings,
  catalog run length, identity states, covers, bounded group routes, last read)
  against stored source rows;
* measures SELECT round trips for the empty, normal, d100, and recovery-fail-open
  paths, including the v2 projection cost after authentication/recovery/mode;
* measures uncompressed and encoded payload size at d100; and
* emits a machine-readable report, including every parity or query-budget
  failure, when ``ROLL_V2_COMPARISON_REPORT`` names an output path.
"""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, Issue, Thread, User
from tests.test_roll_v2_projection import (
    D1,
    D2,
    D4,
    _active_session,
    _catalog_series,
    _confirm_identity,
    _make_thread,
    _rate,
)

D100 = 100
SUMMARY_LIMIT = 20
PROJECTION_QUERY_LIMIT = 3
D100_PAYLOAD_LIMIT_BYTES = 512 * 1024
D100_PER_ITEM_LIMIT_BYTES = 8 * 1024
SERIALIZED_COVER = "https://comicvine.gamespot.com/a/uploads/scale_large/0/1/cover.jpg"

V1_PATH = "/api/v1/roll/bootstrap"
V2_PATH = "/api/v2/roll/bootstrap"


class _SelectRecorder:
    """Count SELECT round trips on one engine and gate the projection window."""

    def __init__(self, engine: AsyncEngine) -> None:
        """Attach a listener and prepare measurement state."""
        self._engine = engine
        self.selects: list[str] = []
        self.projection_selects = 0
        self._in_projection = False

    def _record(
        self,
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        self.selects.append(statement)
        if self._in_projection:
            self.projection_selects += 1

    def reset(self) -> None:
        """Clear recorded statements and the projection counter."""
        self.selects = []
        self.projection_selects = 0

    def begin_projection(self) -> None:
        """Start counting only statements issued inside the v2 projection."""
        self.projection_selects = 0
        self._in_projection = True

    def end_projection(self) -> None:
        """Stop counting projection statements."""
        self._in_projection = False

    def __enter__(self) -> _SelectRecorder:
        """Install the SQL listener."""
        event.listen(self._engine.sync_engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Remove the SQL listener."""
        event.remove(self._engine.sync_engine, "before_cursor_execute", self._record)


def _payload_metrics(response: Response) -> dict[str, int]:
    """Return uncompressed and gzip-encoded payload sizes for one response."""
    content = response.content
    return {
        "uncompressed_bytes": len(content),
        "gzip_bytes": len(gzip.compress(content, compresslevel=9, mtime=0)),
    }


async def _timed_get(
    client: AsyncClient,
    path: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[Response, float]:
    """Call one bootstrap endpoint and return its response and wall time in ms."""
    started = perf_counter()
    response = await client.get(path, params=params, headers=headers)
    return response, (perf_counter() - started) * 1000


def _v1_valid_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return v1 pool rows that carry a non-null next issue."""
    return [row for row in body["roll_pool"] if row.get("issue_id") is not None]


def _v1_null_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return v1 pool rows that carry no next issue id."""
    return [row for row in body["roll_pool"] if row.get("issue_id") is None]


def _check(failures: list[dict[str, Any]], code: str, detail: object) -> None:
    """Record one named harness failure."""
    failures.append({"code": code, "detail": detail})


def _compare_v1_v2(
    v1_body: dict[str, Any],
    v2_body: dict[str, Any],
    *,
    scenario: str,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare every v1-owned bootstrap semantic and return the comparison facts."""
    valid = _v1_valid_rows(v1_body)
    null_rows = _v1_null_rows(v1_body)
    v1_threads = [row["id"] for row in valid]
    v2_items = v2_body["rollable"]
    v2_threads = [item["thread"]["id"] for item in v2_items]

    if v1_threads != v2_threads:
        _check(
            failures,
            "pool.membership_or_ordering",
            {"scenario": scenario, "v1": v1_threads, "v2": v2_threads},
        )

    for expected, actual in zip(valid, v2_items, strict=False):
        if expected["id"] != actual["thread"]["id"]:
            continue
        pairs = {
            "issue.id": (expected["issue_id"], actual["issue"]["id"]),
            "issue.number": (expected["issue_number"], actual["issue"]["number"]),
            "thread.title": (expected["title"], actual["thread"]["title"]),
            "thread.format": (expected["format"], actual["thread"]["format"]),
        }
        for field, (v1_value, v2_value) in pairs.items():
            if v1_value != v2_value:
                _check(
                    failures,
                    f"pool.{field}",
                    {
                        "scenario": scenario,
                        "thread_id": expected["id"],
                        "v1": v1_value,
                        "v2": v2_value,
                    },
                )

    shared_fields = (
        "session_id",
        "user_id",
        "current_die",
        "manual_die",
        "pending_thread_id",
        "last_rolled_result",
        "session_mode",
        "bandwidth",
        "active_thread",
        "roll_recovery",
        "timezone",
        "blocked_count",
        "stale_thread_count",
        "skipped_thread_ids",
    )
    for field in shared_fields:
        if v1_body.get(field) != v2_body.get(field):
            _check(
                failures,
                f"session.{field}",
                {
                    "scenario": scenario,
                    "v1": v1_body.get(field),
                    "v2": v2_body.get(field),
                },
            )

    summary_pairs = {
        "snoozed": (
            [row["id"] for row in v1_body["snoozed_threads"]],
            [row["id"] for row in v2_body["snoozed_threads"]],
            v1_body["snoozed_count"],
            v2_body["snoozed_count"],
        ),
        "skipped": (
            [row["id"] for row in v1_body["skipped_threads"]],
            [row["id"] for row in v2_body["skipped_threads"]],
            len(v1_body["skipped_threads"]),
            len(v2_body["skipped_threads"]),
        ),
        "blocked": (
            [row["id"] for row in v1_body["blocked_threads"]],
            [row["id"] for row in v2_body["blocked_threads"]],
            v1_body["blocked_count"],
            v2_body["blocked_count"],
        ),
    }
    for name, (v1_ids, v2_ids, v1_count, v2_count) in summary_pairs.items():
        if v1_ids != v2_ids or v1_count != v2_count:
            _check(
                failures,
                f"summary.{name}",
                {
                    "scenario": scenario,
                    "v1_ids": v1_ids,
                    "v2_ids": v2_ids,
                    "v1_count": v1_count,
                    "v2_count": v2_count,
                },
            )
        if len(v2_ids) > SUMMARY_LIMIT:
            _check(
                failures,
                f"summary.{name}.unbounded",
                {"scenario": scenario, "count": len(v2_ids), "limit": SUMMARY_LIMIT},
            )

    if (v1_body["stale_thread"] is None) != (v2_body["stale_thread"] is None):
        _check(
            failures,
            "summary.stale_presence",
            {
                "scenario": scenario,
                "v1": v1_body["stale_thread"],
                "v2": v2_body["stale_thread"],
            },
        )

    return {
        "scenario": scenario,
        "v1_pool_rows": len(v1_body["roll_pool"]),
        "v1_rows_without_next_issue": [
            {"thread_id": row["id"], "title": row["title"]} for row in null_rows
        ],
        "v2_rollable_rows": len(v2_items),
    }


async def _assert_null_rows_hold_no_roll_target(
    db: AsyncSession, null_rows: list[dict[str, Any]], failures: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Independently prove v1 null-issue rows cannot be rolled."""
    facts: list[dict[str, Any]] = []
    for row in null_rows:
        thread = await db.get(Thread, row["id"])
        pointed = (
            await db.get(Issue, thread.next_unread_issue_id)
            if thread is not None and thread.next_unread_issue_id is not None
            else None
        )
        valid_target = pointed is not None and pointed.status == "unread"
        facts.append(
            {
                "thread_id": row["id"],
                "title": row["title"],
                "next_unread_issue_id": None if thread is None else thread.next_unread_issue_id,
                "pointed_issue_status": None if pointed is None else pointed.status,
                "valid_roll_target": valid_target,
            }
        )
        if valid_target:
            _check(failures, "v1_null_row_has_valid_target", facts[-1])
    return facts


def _validate_v2_enrichment(
    v2_body: dict[str, Any],
    *,
    session_id: int,
    expected_last_read_at: datetime,
    failures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate v2-only fields against independently built stored fixtures."""
    items = {item["thread"]["title"]: item for item in v2_body["rollable"]}
    result: dict[str, Any] = {"checks": []}

    def require(condition: bool, code: str, detail: object) -> None:
        result["checks"].append({"code": code, "passed": condition})
        if not condition:
            _check(failures, code, detail)

    split = [items.get("Thanos A"), items.get("Thanos B")]
    require(
        all(item is not None for item in split),
        "split.fixtures_present",
        sorted(items),
    )
    if all(item is not None for item in split):
        for item in split:
            assert item is not None
            require(
                item["identity"]["canonical_series_id"] == "20764",
                "split.canonical_series_id",
                item["identity"],
            )
            require(
                item["reader"]["rating_count"] == 2
                and item["reader"]["average_rating"] == pytest.approx(3.0)
                and item["reader"]["read_count"] == 4,
                "split.effective_ratings",
                item["reader"],
            )
            require(
                item["reader"]["progress_scope"] == "canonical_series_run"
                and item["reader"]["issue_count"] == 12,
                "split.catalog_run_length",
                item["reader"],
            )

    mixed = items.get("Mixed")
    require(mixed is not None, "composite.fixture_present", sorted(items))
    if mixed is not None:
        require(
            mixed["identity"]["canonical_series_id"] == "2"
            and mixed["issue"]["canonical_series_title"] == "Beta",
            "composite.next_issue_scope",
            mixed["identity"],
        )
        require(
            mixed["reader"]["rating_count"] == 0
            and mixed["reader"]["average_rating"] is None,
            "composite.no_volume_flattening",
            mixed["reader"],
        )

    unresolved = items.get("Unresolved")
    require(unresolved is not None, "unresolved.fixture_present", sorted(items))
    if unresolved is not None:
        require(
            unresolved["identity"]["state"] == "unresolved"
            and unresolved["identity"]["canonical_series_id"] is None,
            "unresolved.identity_truthful",
            unresolved["identity"],
        )
        require(
            unresolved["reader"]["progress_scope"] == "thread",
            "unresolved.thread_progress",
            unresolved["reader"],
        )

    covered = items.get("Covered")
    bare = items.get("Bare")
    require(covered is not None and bare is not None, "cover.fixtures_present", sorted(items))
    if covered is not None and bare is not None:
        require(
            covered["issue"]["cover_url"] == SERIALIZED_COVER,
            "cover.direct_provider_url",
            covered["issue"],
        )
        require(
            "/api/v1/images/optimize" not in (covered["issue"]["cover_url"] or ""),
            "cover.no_retired_proxy",
            covered["issue"],
        )
        require(bare["issue"]["cover_url"] is None, "cover.missing_is_null", bare["issue"])

    routed = items.get("Routed")
    require(routed is not None, "routes.fixture_present", sorted(items))
    if routed is not None:
        require(
            v2_body["active_thread"] is not None
            and v2_body["active_thread"]["id"] == routed["thread"]["id"]
            and v2_body["last_rolled_result"] == 4
            and v2_body["pending_thread_id"] is None,
            "active_thread.rolled_state",
            {
                "active_thread": v2_body["active_thread"],
                "last_rolled_result": v2_body["last_rolled_result"],
                "pending_thread_id": v2_body["pending_thread_id"],
            },
        )
        require(len(routed["routes"]) <= 3, "routes.bounded", routed["routes"])
        require(
            all(route["kind"] == "group" for route in routed["routes"]),
            "routes.group_kind",
            routed["routes"],
        )
        require(
            routed["overflow_routes_count"] == 2,
            "routes.overflow_count",
            routed["overflow_routes_count"],
        )

    last_read = v2_body["last_read"]
    require(last_read is not None, "last_read.present", last_read)
    if last_read is not None:
        require(
            last_read["thread_title"] == "Routed"
            and last_read["issue_number"] == "1"
            and last_read["read_at"] is not None
            and datetime.fromisoformat(last_read["read_at"]).replace(tzinfo=UTC).timestamp()
            == expected_last_read_at.timestamp(),
            "last_read.latest_session_rate_event",
            last_read,
        )
        require(
            routed is not None and last_read["thread_id"] == routed["thread"]["id"],
            "last_read.thread_scope",
            last_read,
        )

    require(v2_body["session_id"] == session_id, "session.id", v2_body["session_id"])
    require(
        v2_body["current_die"] == D100 and v2_body["manual_die"] == D100,
        "die.manual_and_current",
        {"current_die": v2_body["current_die"], "manual_die": v2_body["manual_die"]},
    )
    return result


@pytest.mark.asyncio
async def test_production_shaped_v1_v2_comparison_harness(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Prove v1/v2 parity, v2 enrichment, query budgets, and bounded payloads."""
    report: dict[str, Any] = {
        "issue": 2718,
        "harness": "tests/test_roll_bootstrap_comparison.py",
        "head_fixture": "production-shaped",
        "scenarios": [],
        "parity": [],
        "v2_only_validation": {},
        "special_fixtures": [
            "split_canonical_series",
            "composite_mixed_volume_thread",
            "unresolved_identity",
            "missing_cover",
            "recovery_fail_open",
            "v1_null_issue_row",
        ],
        "query_budget": {
            "limit_after_auth": PROJECTION_QUERY_LIMIT,
            "measurements": [],
        },
        "payloads": [],
        "failures": [],
    }
    failures: list[dict[str, Any]] = report["failures"]

    session = await _active_session(async_db, default_user)

    # Split canonical series: two ComicPile threads share one stored volume.
    _, split_a = await _make_thread(
        async_db,
        default_user,
        title="Thanos A",
        issue_count=3,
        queue_position=1,
        read_through=2,
    )
    _, split_b = await _make_thread(
        async_db,
        default_user,
        title="Thanos B",
        issue_count=3,
        queue_position=2,
        read_through=2,
    )
    for position, issue in enumerate(split_a):
        await _confirm_identity(
            async_db,
            issue,
            external_id=f"20764-a-{position}",
            series_id=20764,
            series_name="Thanos",
        )
    for position, issue in enumerate(split_b):
        await _confirm_identity(
            async_db,
            issue,
            external_id=f"20764-b-{position}",
            series_id=20764,
            series_name="Thanos",
        )
    await _catalog_series(
        async_db, external_id="20764", name="Thanos", count_of_issues=12
    )
    await _rate(async_db, split_a[0], rating=4.0, timestamp=D1)
    await _rate(async_db, split_b[0], rating=2.0, timestamp=D2)

    # Composite/mixed-volume thread: the next unread issue decides the volume.
    _, mixed = await _make_thread(
        async_db,
        default_user,
        title="Mixed",
        issue_count=3,
        queue_position=3,
        read_through=2,
    )
    await _confirm_identity(
        async_db, mixed[0], external_id="1-mixed-0", series_id=1, series_name="Alpha"
    )
    await _confirm_identity(
        async_db, mixed[1], external_id="2-mixed-1", series_id=1, series_name="Alpha"
    )
    await _confirm_identity(
        async_db, mixed[2], external_id="3-mixed-2", series_id=2, series_name="Beta"
    )
    await _rate(async_db, mixed[0], rating=5.0, timestamp=D1)

    # No stored identity evidence at all.
    await _make_thread(
        async_db,
        default_user,
        title="Unresolved",
        issue_count=2,
        queue_position=4,
    )

    # Direct provider cover and a deliberately missing cover.
    _, covered = await _make_thread(
        async_db,
        default_user,
        title="Covered",
        issue_count=2,
        queue_position=5,
        read_through=1,
    )
    _, bare = await _make_thread(
        async_db,
        default_user,
        title="Bare",
        issue_count=2,
        queue_position=6,
        read_through=1,
    )
    await _confirm_identity(
        async_db,
        covered[1],
        external_id="cover-present",
        series_id=5,
        series_name="Covered",
        image_url=SERIALIZED_COVER,
    )
    await _confirm_identity(
        async_db, bare[1], external_id="cover-missing", series_id=6, series_name="Bare"
    )

    # Bounded group routes plus the session's latest read event.
    routed, routed_issues = await _make_thread(
        async_db,
        default_user,
        title="Routed",
        issue_count=2,
        queue_position=7,
        read_through=1,
    )
    for index in range(5):
        from app.models.dependency_group import DependencyGroup, DependencyGroupMembership

        group = DependencyGroup(user_id=default_user.id, name=f"Crossover {index:02d}")
        async_db.add(group)
        await async_db.flush()
        async_db.add(
            DependencyGroupMembership(
                group_id=group.id,
                thread_id=routed.id if index % 2 == 0 else None,
                issue_id=routed_issues[1].id if index % 2 == 1 else None,
            )
        )
    await async_db.flush()
    await _rate(
        async_db,
        routed_issues[0],
        rating=4.5,
        timestamp=D4,
        session_id=session.id,
    )
    async_db.add(
        Event(
            type="roll",
            session_id=session.id,
            selected_thread_id=routed.id,
            result=4,
            timestamp=datetime(2026, 1, 5, tzinfo=UTC),
        )
    )
    await async_db.flush()

    # Exhausted thread: v1 reports a null issue id, v2 must omit it. Keep it
    # behind the d100 window so the d100 scenario itself yields 100 valid rows.
    await _make_thread(
        async_db,
        default_user,
        title="Exhausted",
        issue_count=1,
        queue_position=999,
        read_through=1,
    )

    # Bounded summaries: 22 snoozed and 22 skipped-series rows plus one stale.
    snoozed_ids = []
    for index in range(22):
        thread, _ = await _make_thread(
            async_db,
            default_user,
            title=f"Snoozed {index:02d}",
            issue_count=1,
            queue_position=100 + index,
        )
        snoozed_ids.append(thread.id)
    skipped_ids = []
    for index in range(22):
        thread, _ = await _make_thread(
            async_db,
            default_user,
            title=f"Skipped {index:02d}",
            issue_count=1,
            queue_position=200 + index,
        )
        skipped_ids.append(thread.id)
    stale_thread, _ = await _make_thread(
        async_db,
        default_user,
        title="Stale",
        issue_count=1,
        queue_position=300,
    )
    stale_thread.last_activity_at = datetime.now(UTC) - timedelta(days=30)
    session.snoozed_thread_ids = snoozed_ids
    session.skipped_thread_ids = skipped_ids
    await async_db.flush()

    with _SelectRecorder(db_engine) as recorder:
        # Empty pool: temporarily snooze every rollable thread except one so the
        # fixture library exists but the projection returns no rows.
        empty_snoozed = [thread.id for thread in await _rollable_threads(async_db, default_user)]
        session.snoozed_thread_ids = empty_snoozed
        await async_db.flush()

        recorder.reset()
        v1_empty, v1_empty_ms = await _timed_get(
            auth_client, V1_PATH, params={"timezone": "America/New_York"}
        )
        v1_empty_selects = len(recorder.selects)
        v1_empty_payload = _payload_metrics(v1_empty)

        recorder.reset()
        v2_empty, v2_empty_ms = await _timed_get(
            auth_client, V2_PATH, params={"timezone": "America/New_York"}
        )
        v2_empty_selects = len(recorder.selects)
        v2_empty_payload = _payload_metrics(v2_empty)

        if v1_empty.status_code != 200 or v2_empty.status_code != 200:
            _check(
                failures,
                "empty.status",
                {"v1": v1_empty.status_code, "v2": v2_empty.status_code},
            )
        v1_empty_body = v1_empty.json()
        v2_empty_body = v2_empty.json()
        if v2_empty_body["rollable"] != []:
            _check(
                failures,
                "empty.v2_pool_not_empty",
                len(v2_empty_body["rollable"]),
            )
        if any(row["issue_id"] is not None for row in v1_empty_body["roll_pool"]):
            _check(
                failures,
                "empty.v1_valid_target_present",
                [
                    {"thread_id": row["id"], "issue_id": row["issue_id"]}
                    for row in v1_empty_body["roll_pool"]
                    if row["issue_id"] is not None
                ],
            )
        report["scenarios"].append(
            {
                "name": "empty",
                "v1_selects": v1_empty_selects,
                "v2_selects": v2_empty_selects,
                "v1_latency_ms": round(v1_empty_ms, 2),
                "v2_latency_ms": round(v2_empty_ms, 2),
                "v1_payload": v1_empty_payload,
                "v2_payload": v2_empty_payload,
            }
        )
        report["parity"].append(
            _compare_v1_v2(
                v1_empty_body, v2_empty_body, scenario="empty", failures=failures
            )
        )
        report["parity"][-1]["v1_rows_without_next_issue"] = (
            await _assert_null_rows_hold_no_roll_target(
                async_db, _v1_null_rows(v1_empty_body), failures
            )
        )

        # Normal pool: every special fixture is rollable again. The die bounds
        # the pool, so use a d100-sized die to keep all fixtures in scope.
        session.snoozed_thread_ids = snoozed_ids
        session.manual_die = D100
        await async_db.flush()

        recorder.reset()
        v1_normal, v1_normal_ms = await _timed_get(auth_client, V1_PATH)
        v1_normal_selects = len(recorder.selects)
        v1_normal_payload = _payload_metrics(v1_normal)

        # Count the v2 projection statement window separately from auth,
        # recovery, mode, and summary lookups.
        original_projection = _projection_symbol()
        calls: dict[str, int] = {"count": 0}

        async def _counted_projection(*args: object, **kwargs: object) -> object:
            calls["count"] += 1
            recorder.begin_projection()
            try:
                return await original_projection(*args, **kwargs)
            finally:
                recorder.end_projection()

        monkeypatch.setattr("app.api.roll.get_v2_rollable_projection", _counted_projection)

        recorder.reset()
        v2_normal, v2_normal_ms = await _timed_get(auth_client, V2_PATH)
        v2_normal_selects = len(recorder.selects)
        v2_projection_selects = recorder.projection_selects
        v2_normal_payload = _payload_metrics(v2_normal)

        monkeypatch.undo()

        if v1_normal.status_code != 200 or v2_normal.status_code != 200:
            _check(
                failures,
                "normal.status",
                {"v1": v1_normal.status_code, "v2": v2_normal.status_code},
            )
        if calls["count"] != 1:
            _check(failures, "v2.projection_call_count", calls["count"])
        if not 1 <= v2_projection_selects <= PROJECTION_QUERY_LIMIT:
            _check(
                failures,
                "query_budget.projection",
                {
                    "scenario": "normal",
                    "selects": v2_projection_selects,
                    "limit": PROJECTION_QUERY_LIMIT,
                },
            )

        v1_normal_body = v1_normal.json()
        v2_normal_body = v2_normal.json()
        report["scenarios"].append(
            {
                "name": "normal",
                "v1_selects": v1_normal_selects,
                "v2_selects": v2_normal_selects,
                "v2_projection_selects_after_auth": v2_projection_selects,
                "v1_latency_ms": round(v1_normal_ms, 2),
                "v2_latency_ms": round(v2_normal_ms, 2),
                "v1_payload": v1_normal_payload,
                "v2_payload": v2_normal_payload,
            }
        )
        report["parity"].append(
            _compare_v1_v2(
                v1_normal_body, v2_normal_body, scenario="normal", failures=failures
            )
        )
        report["query_budget"]["measurements"].append(
            {
                "scenario": "normal",
                "v1_selects": v1_normal_selects,
                "v2_selects": v2_normal_selects,
                "v2_projection_selects_after_auth": v2_projection_selects,
                "limit": PROJECTION_QUERY_LIMIT,
                "passed": 1 <= v2_projection_selects <= PROJECTION_QUERY_LIMIT,
            }
        )
        report["v2_only_validation"] = _validate_v2_enrichment(
            v2_normal_body,
            session_id=session.id,
            expected_last_read_at=D4,
            failures=failures,
        )
        report["parity"][-1]["v1_rows_without_next_issue"] = (
            await _assert_null_rows_hold_no_roll_target(
                async_db, _v1_null_rows(v1_normal_body), failures
            )
        )

        # d100 pool: add filler threads until the projection returns 100 rows.
        current_rollable = len(v2_normal_body["rollable"])
        next_position = 400
        for index in range(current_rollable, D100):
            await _make_thread(
                async_db,
                default_user,
                title=f"Bulk {index:03d}",
                issue_count=2,
                queue_position=next_position,
            )
            next_position += 1
        await async_db.flush()

        recorder.reset()
        v1_d100, v1_d100_ms = await _timed_get(auth_client, V1_PATH)
        v1_d100_selects = len(recorder.selects)
        v1_d100_payload = _payload_metrics(v1_d100)

        d100_projection = _projection_symbol()

        async def _counted_d100_projection(*args: object, **kwargs: object) -> object:
            recorder.begin_projection()
            try:
                return await d100_projection(*args, **kwargs)
            finally:
                recorder.end_projection()

        monkeypatch.setattr("app.api.roll.get_v2_rollable_projection", _counted_d100_projection)

        recorder.reset()
        v2_d100, v2_d100_ms = await _timed_get(auth_client, V2_PATH)
        v2_d100_selects = len(recorder.selects)
        v2_d100_projection_selects = recorder.projection_selects
        v2_d100_payload = _payload_metrics(v2_d100)

        monkeypatch.undo()

        if not 1 <= v2_d100_projection_selects <= PROJECTION_QUERY_LIMIT:
            _check(
                failures,
                "query_budget.projection_d100",
                {
                    "scenario": "d100",
                    "selects": v2_d100_projection_selects,
                    "limit": PROJECTION_QUERY_LIMIT,
                },
            )

        if v1_d100.status_code != 200 or v2_d100.status_code != 200:
            _check(
                failures,
                "d100.status",
                {"v1": v1_d100.status_code, "v2": v2_d100.status_code},
            )
        v1_d100_body = v1_d100.json()
        v2_d100_body = v2_d100.json()
        d100_items = len(v2_d100_body["rollable"])
        if d100_items != D100:
            _check(failures, "d100.row_count", d100_items)
        if v2_d100_selects != v2_normal_selects:
            _check(
                failures,
                "query_budget.d100_growth",
                {"normal": v2_normal_selects, "d100": v2_d100_selects},
            )
        per_item = v2_d100_payload["uncompressed_bytes"] / max(1, d100_items)
        if v2_d100_payload["uncompressed_bytes"] > D100_PAYLOAD_LIMIT_BYTES:
            _check(
                failures,
                "payload.d100_total",
                {
                    "bytes": v2_d100_payload["uncompressed_bytes"],
                    "limit": D100_PAYLOAD_LIMIT_BYTES,
                },
            )
        if per_item > D100_PER_ITEM_LIMIT_BYTES:
            _check(
                failures,
                "payload.d100_per_item",
                {"bytes_per_item": round(per_item, 2), "limit": D100_PER_ITEM_LIMIT_BYTES},
            )
        if v2_d100_payload["gzip_bytes"] >= v2_d100_payload["uncompressed_bytes"]:
            _check(
                failures,
                "payload.d100_encoding",
                {"gzip": v2_d100_payload, "uncompressed": v2_d100_payload},
            )

        report["scenarios"].append(
            {
                "name": "d100",
                "rows": d100_items,
                "v1_selects": v1_d100_selects,
                "v2_selects": v2_d100_selects,
                "v2_projection_selects_after_auth": v2_d100_projection_selects,
                "v1_latency_ms": round(v1_d100_ms, 2),
                "v2_latency_ms": round(v2_d100_ms, 2),
                "v1_payload": v1_d100_payload,
                "v2_payload": v2_d100_payload,
                "v2_bytes_per_item": round(per_item, 2),
            }
        )
        report["query_budget"]["measurements"].append(
            {
                "scenario": "d100",
                "v1_selects": v1_d100_selects,
                "v2_selects": v2_d100_selects,
                "v2_projection_selects_after_auth": v2_d100_projection_selects,
                "limit": PROJECTION_QUERY_LIMIT,
                "passed": 1 <= v2_d100_projection_selects <= PROJECTION_QUERY_LIMIT,
            }
        )
        report["payloads"].append(
            {
                "scenario": "d100",
                "rows": d100_items,
                "v1_uncompressed_bytes": v1_d100_payload["uncompressed_bytes"],
                "v1_gzip_bytes": v1_d100_payload["gzip_bytes"],
                "v2_uncompressed_bytes": v2_d100_payload["uncompressed_bytes"],
                "v2_gzip_bytes": v2_d100_payload["gzip_bytes"],
                "v2_bytes_per_item": round(per_item, 2),
                "limits": {
                    "uncompressed_bytes": D100_PAYLOAD_LIMIT_BYTES,
                    "bytes_per_item": D100_PER_ITEM_LIMIT_BYTES,
                },
            }
        )
        report["parity"].append(
            _compare_v1_v2(
                v1_d100_body, v2_d100_body, scenario="d100", failures=failures
            )
        )

        # Recovery-fail-open: a continuity-capacity failure must still return a
        # valid bootstrap for both aliases with roll_recovery omitted.
        from fastapi import HTTPException

        from app import roll_recovery

        async def _too_large(*args: object, **kwargs: object) -> object:
            raise HTTPException(
                status_code=422,
                detail={"code": "continuity_graph_too_large", "limit": 5000},
            )

        session.pending_thread_id = routed.id
        await async_db.flush()
        with monkeypatch.context() as recovery_patch:
            recovery_patch.setattr(roll_recovery, "resolve_continuity_chains", _too_large)

            recorder.reset()
            v1_recovery, v1_recovery_ms = await _timed_get(auth_client, V1_PATH)
            v1_recovery_selects = len(recorder.selects)

            recorder.reset()
            v2_recovery, v2_recovery_ms = await _timed_get(auth_client, V2_PATH)
            v2_recovery_selects = len(recorder.selects)

        if v1_recovery.status_code != 200 or v2_recovery.status_code != 200:
            _check(
                failures,
                "recovery.status",
                {"v1": v1_recovery.status_code, "v2": v2_recovery.status_code},
            )
        v1_recovery_body = v1_recovery.json()
        v2_recovery_body = v2_recovery.json()
        if v1_recovery_body["roll_recovery"] is not None:
            _check(
                failures,
                "recovery.v1_not_fail_open",
                v1_recovery_body["roll_recovery"],
            )
        if v2_recovery_body["roll_recovery"] is not None:
            _check(
                failures,
                "recovery.v2_not_fail_open",
                v2_recovery_body["roll_recovery"],
            )
        if v2_recovery_body["pending_thread_id"] != routed.id:
            _check(
                failures,
                "recovery.pending_thread_lost",
                v2_recovery_body["pending_thread_id"],
            )
        report["scenarios"].append(
            {
                "name": "recovery_fail_open",
                "v1_selects": v1_recovery_selects,
                "v2_selects": v2_recovery_selects,
                "v1_latency_ms": round(v1_recovery_ms, 2),
                "v2_latency_ms": round(v2_recovery_ms, 2),
            }
        )
        report["query_budget"]["measurements"].append(
            {
                "scenario": "recovery_fail_open",
                "v1_selects": v1_recovery_selects,
                "v2_selects": v2_recovery_selects,
            }
        )
        report["parity"].append(
            _compare_v1_v2(
                v1_recovery_body,
                v2_recovery_body,
                scenario="recovery_fail_open",
                failures=failures,
            )
        )

    report["passed"] = not failures
    report["notes"] = [
        "Latency values are single local-run wall times, not production SLOs.",
        "v1 does not expose thread.last_activity_at; v2 exposes it as enrichment.",
        "Cover URLs are direct provider URLs per #4177; the retired image optimizer is not expected.",
        "A v1 pool row with a null issue id is listed with independent proof it has no readable target.",
    ]
    report["query_budget"]["passed"] = not any(
        failure["code"].startswith("query_budget") for failure in failures
    )

    output_path = os.environ.get("ROLL_V2_COMPARISON_REPORT")
    if output_path:
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    else:
        fallback = tmp_path_factory.mktemp("roll-v2-comparison") / "report.json"
        with open(fallback, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    print(f"ROLL_V2_COMPARISON_REPORT={output_path or fallback}")
    print("ROLL_V2_COMPARISON_JSON=" + json.dumps(report, sort_keys=True))

    assert not failures, json.dumps(failures, indent=2, sort_keys=True)


async def _rollable_threads(db: AsyncSession, user: User) -> list[Thread]:
    """Return the user's active threads that still hold an unread issue."""
    from sqlalchemy import select

    rows = await db.scalars(
        select(Thread).where(
            Thread.user_id == user.id,
            Thread.status == "active",
            Thread.is_blocked.is_(False),
            Thread.next_unread_issue_id.is_not(None),
        )
    )
    return list(rows.all())


def _projection_symbol() -> Callable[..., Awaitable[object]]:
    """Return the current v2 projection callable used by the API module."""
    from app.api import roll

    symbol: Callable[..., Awaitable[object]] = roll.get_v2_rollable_projection
    return symbol
