"""Measured SQL-budget regressions for the native v2 Roll commands (#5151).

Each case sends one real authenticated request through the mounted Rust router
against the canonical Alembic schema. PostgreSQL statements are measured under
the isolated ``roll_test_dml`` role with ``pg_stat_statements.track=all``.
Application statements, transaction controls, checkout probes, and nested
trigger statements are measured separately. Small and large reader fixtures
prove that the statement count does not grow with library size.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
from jose import jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models import Event, Issue, ReadingSession, Thread, User
from route_harness import (
    SQL_BUDGET_SOURCES,
    StatementBreakdown,
    assert_declared_budget,
    assert_measured_statement_breakdown,
    assert_no_statement_growth,
    cargo_example_path,
    db_statement_breakdown,
    run_rust_example,
)

SECRET = "synthetic-native-roll-commands-n1-secret"
BINARY = str(cargo_example_path("http_roll_commands"))
SMALL_LIBRARY_SIZE = 5
LARGE_LIBRARY_SIZE = 200
ROLL_ROUTES = (
    ("POST", "/api/v2/roll/dice-command"),
    ("GET", "/api/v2/roll/die-state"),
    ("POST", "/api/v2/roll/offer"),
    ("POST", "/api/v2/roll/reset"),
)


@dataclass(frozen=True)
class ReaderFixture:
    """One canonical-schema reader used by a Roll budget measurement."""

    user_id: int
    session_id: int
    username: str
    token: str
    thread_ids: tuple[int, ...]
    issue_ids: tuple[int, ...]


@dataclass(frozen=True)
class RouteMeasurement:
    """One HTTP response and its isolated PostgreSQL statement split."""

    response: dict[str, object]
    statements: StatementBreakdown


def _token(username: str) -> str:
    """Return a signed access token for one synthetic reader."""
    return jwt.encode(
        {
            "sub": username,
            "jti": f"jti-{uuid4().hex}",
            "type": "access",
            "exp": 4_102_444_800,
        },
        SECRET,
        algorithm="HS256",
    )


async def _seed_reader(
    engine: AsyncSession,
    *,
    library_size: int,
    prefix: str,
    initial_die: int | None = None,
    pending_selection: bool = False,
) -> ReaderFixture:
    """Seed one reader, active session, and canonical thread/issue library."""
    username = f"{prefix}_{uuid4().hex[:12]}"
    owner = User(username=username)
    engine.add(owner)
    await engine.flush()

    threads = [
        Thread(
            user_id=owner.id,
            title=f"Series {index + 1}",
            format="Comic",
            issues_remaining=1,
            total_issues=1,
            queue_position=index + 1,
            status="active",
        )
        for index in range(library_size)
    ]
    engine.add_all(threads)
    await engine.flush()

    issues = [
        Issue(
            thread_id=thread.id,
            issue_number="1",
            position=1,
            status="unread",
        )
        for thread in threads
    ]
    engine.add_all(issues)
    await engine.flush()
    for thread, issue in zip(threads, issues, strict=True):
        thread.next_unread_issue_id = issue.id

    session = ReadingSession(
        user_id=owner.id,
        started_at=datetime.now(UTC),
        start_die=6,
    )
    if pending_selection:
        session.pending_thread_id = threads[0].id
        session.pending_issue_id = issues[0].id
        session.pending_thread_updated_at = datetime.now(UTC)
        session.manual_die = 20
    engine.add(session)
    if initial_die is not None:
        engine.add(
            Event(
                user_id=owner.id,
                type="manual_die",
                die=initial_die,
                die_after=initial_die,
                timestamp=datetime.now(UTC),
            )
        )
    await engine.commit()

    return ReaderFixture(
        user_id=owner.id,
        session_id=session.id,
        username=username,
        token=_token(username),
        thread_ids=tuple(thread.id for thread in threads),
        issue_ids=tuple(issue.id for issue in issues),
    )


async def _measure_route(
    engine: AsyncSession,
    *,
    method: str,
    path: str,
    token: str,
    body: dict[str, object] | None = None,
) -> RouteMeasurement:
    """Run one mounted request and measure its isolated statement split."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    env = {
        **os.environ,
        "RUST_ROLL_DATABASE_URL": url,
        "RUST_ROLL_JWT_SECRET": SECRET,
        "RUST_ROLL_POOL_SIZE": "2",
        "RUST_ROLL_TEST_TOKEN": token,
        "RUST_ROLL_TEST_METHOD": method,
        "RUST_ROLL_TEST_URI": path,
    }
    if body is not None:
        env["RUST_ROLL_TEST_BODY"] = json.dumps(body)

    before = await db_statement_breakdown(engine)
    response, _, _, _ = await run_rust_example(BINARY, env)
    after = await db_statement_breakdown(engine)
    assert before is not None and after is not None, "pg_stat_statements is required"
    measured = StatementBreakdown(
        application=after.application - before.application,
        transaction_control=after.transaction_control - before.transaction_control,
        runtime_overhead=after.runtime_overhead - before.runtime_overhead,
        nested=after.nested - before.nested,
    )
    print(
        f"route={method} {path} statements={measured}",
        flush=True,
    )
    return RouteMeasurement(response=response, statements=measured)


def _assert_route_budget(
    method: str,
    path: str,
    small: RouteMeasurement,
    large: RouteMeasurement,
) -> None:
    """Enforce absolute, growth, and nested budgets for one route pair."""
    assert_measured_statement_breakdown(method, path, small.statements)
    assert_measured_statement_breakdown(method, path, large.statements)
    assert_declared_budget(method, path, small.statements.top_level, large.statements.top_level)
    assert_no_statement_growth(method, path, small.statements.top_level, large.statements.top_level)
    assert small.statements.nested == large.statements.nested


@pytest.mark.asyncio
async def test_dice_command_statements_do_not_grow_with_library_size() -> None:
    """The manual-die command stays fixed while the owned library grows."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            small_reader = await _seed_reader(
                db,
                library_size=SMALL_LIBRARY_SIZE,
                prefix="dice_small",
            )
            large_reader = await _seed_reader(
                db,
                library_size=LARGE_LIBRARY_SIZE,
                prefix="dice_large",
            )

        small = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/dice-command",
            token=small_reader.token,
            body={
                "kind": "manual_select",
                "die": 12,
                "idempotency_key": f"dice-small-{uuid4().hex}",
            },
        )
        large = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/dice-command",
            token=large_reader.token,
            body={
                "kind": "manual_select",
                "die": 12,
                "idempotency_key": f"dice-large-{uuid4().hex}",
            },
        )

        for measurement in (small, large):
            assert measurement.response.get("status") == 200, measurement.response
            body = measurement.response.get("body")
            assert isinstance(body, dict)
            assert isinstance(body.get("event_id"), int)
            assert body.get("die_before") == 6
            assert body.get("die_after") == 12
            assert body.get("replayed") is False

        async with AsyncSession(engine, expire_on_commit=False) as db:
            event_count = await db.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.user_id == small_reader.user_id,
                    Event.type == "manual_die",
                )
            )
        assert event_count == 1
        _assert_route_budget(
            "POST",
            "/api/v2/roll/dice-command",
            small,
            large,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_offer_statements_do_not_grow_with_candidate_library_size() -> None:
    """The offer remains set-based for five and 200 eligible candidates."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            small_reader = await _seed_reader(
                db,
                library_size=SMALL_LIBRARY_SIZE,
                prefix="offer_small",
            )
            large_reader = await _seed_reader(
                db,
                library_size=LARGE_LIBRARY_SIZE,
                prefix="offer_large",
            )

        small = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/offer",
            token=small_reader.token,
            body={"idempotency_key": f"offer-small-{uuid4().hex}"},
        )
        large = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/offer",
            token=large_reader.token,
            body={"idempotency_key": f"offer-large-{uuid4().hex}"},
        )

        for measurement, reader in (
            (small, small_reader),
            (large, large_reader),
        ):
            assert measurement.response.get("status") == 200, measurement.response
            body = measurement.response.get("body")
            assert isinstance(body, dict)
            assert body.get("thread_id") in reader.thread_ids
            assert body.get("issue_id") in reader.issue_ids
            assert body.get("title", "").startswith("Series ")
            assert body.get("format") == "Comic"
            assert body.get("issues_remaining") == 1
            assert body.get("die_size") == 6
            assert isinstance(body.get("result"), int)
            assert 1 <= body["result"] <= 6
            assert body.get("issue_number") == "1"
            assert body.get("next_issue_id") == body.get("issue_id")
            assert body.get("next_issue_number") == "1"
            assert body.get("total_issues") == 1
            assert body.get("snoozed_count") == 0
            assert body.get("snoozed_thread_id") is None

        async with AsyncSession(engine, expire_on_commit=False) as db:
            event_count = await db.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.user_id == large_reader.user_id,
                    Event.type == "roll",
                )
            )
        assert event_count == 1
        _assert_route_budget("POST", "/api/v2/roll/offer", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reset_statements_do_not_grow_with_library_size() -> None:
    """Reset stays fixed while the owned library grows and clears its pending offer."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            small_reader = await _seed_reader(
                db,
                library_size=SMALL_LIBRARY_SIZE,
                prefix="reset_small",
                initial_die=20,
                pending_selection=True,
            )
            large_reader = await _seed_reader(
                db,
                library_size=LARGE_LIBRARY_SIZE,
                prefix="reset_large",
                initial_die=20,
                pending_selection=True,
            )

        small = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/reset",
            token=small_reader.token,
            body={"idempotency_key": f"reset-small-{uuid4().hex}"},
        )
        large = await _measure_route(
            engine,
            method="POST",
            path="/api/v2/roll/reset",
            token=large_reader.token,
            body={"idempotency_key": f"reset-large-{uuid4().hex}"},
        )

        for measurement in (small, large):
            assert measurement.response.get("status") == 200, measurement.response
            assert measurement.response.get("body") == {"die": 6, "replayed": False}

        async with AsyncSession(engine, expire_on_commit=False) as db:
            reset_event_count = await db.scalar(
                select(func.count())
                .select_from(Event)
                .where(
                    Event.user_id == small_reader.user_id,
                    Event.type == "reset_dice",
                )
            )
            session = await db.get(ReadingSession, small_reader.session_id)
        assert reset_event_count == 1
        assert session is not None
        assert session.pending_thread_id is None
        assert session.pending_issue_id is None
        assert session.manual_die is None
        _assert_route_budget("POST", "/api/v2/roll/reset", small, large)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), ROLL_ROUTES)
async def test_extra_and_n_plus_one_queries_fail_roll_budget_guards(
    method: str,
    path: str,
) -> None:
    """A deliberate extra query and a per-row-style burst fail the route guards."""
    url = os.environ["RUST_ROLL_PARITY_DATABASE_URL"]
    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        before = await db_statement_breakdown(engine)
        assert before is not None
        connection = await asyncpg.connect(url)
        try:
            await connection.execute("SELECT 42::integer AS deliberate_extra_query")
            for _ in range(3):
                await connection.execute(
                    "SELECT 43::integer AS deliberate_n_plus_one_query"
                )
        finally:
            await connection.close()
        after = await db_statement_breakdown(engine)
        assert after is not None
        assert after.application - before.application == 4
        assert after.top_level > before.top_level

        document = json.loads(SQL_BUDGET_SOURCES.read_text(encoding="utf-8"))
        entries = [
            entry
            for entry in document["operations"]
            if entry["method"] == method and entry["path"] == path
        ]
        assert len(entries) == 1
        maximum = entries[0]["sql_budget"]["max_statements"]
        with pytest.raises(AssertionError, match="declared maximum"):
            assert_declared_budget(method, path, maximum + 1)
        with pytest.raises(AssertionError, match="grew with data size"):
            assert_no_statement_growth(method, path, before.top_level, after.top_level)
    finally:
        await engine.dispose()
