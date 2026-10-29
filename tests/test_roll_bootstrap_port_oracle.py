"""Record the actual Python v1 bootstrap contract and SQL for its Rust port.

Only fixture-owned synthetic test records are used. This is a reference export,
not a claim that a native implementation matches or serves production traffic.

The synthetic request runs on its own connection with real transaction
boundaries. Setup fixtures are committed first, and the request session is
created fresh from the shared engine so the recorded transcript captures the
same begin/commit/rollback shape a live client sees instead of test savepoints.
"""

import json
import os
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from scripts.rust_endpoint_oracle import SqlTranscript, operation_contract, render
from tests.conftest import _create_async_db_override, get_or_create_user_async
from tests.test_roll_bootstrap_query_budget import _populate_library

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "native/contracts/roll-bootstrap-v1.openapi.json"
ROUTE = "/api/v1/roll/bootstrap"


def test_python_bootstrap_matches_frozen_operation() -> None:
    """Pin the actual FastAPI operation, not just a potentially stale generated file."""
    actual = operation_contract(app.openapi(), ROUTE, "get")
    assert render(actual) == CONTRACT.read_text()


@pytest.mark.asyncio
async def test_record_populated_bootstrap_sql(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """Exercise all v1 library sections and export SQL/binds/transaction ordering.

    Fixtures are committed on their own session so the request sees durable
    rows. The request then runs through a fresh session created from the same
    engine, so its transaction boundaries are real and fully recorded.
    """
    user = await get_or_create_user_async(async_db_committed)
    await _populate_library(async_db_committed, user.id, rollable_count=8)

    # Fresh request session: real begin/commit/rollback, no shared savepoint.
    app.dependency_overrides[get_db] = await _create_async_db_override()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        csrf_token = generate_csrf_token()
        client.cookies.set(CSRF_COOKIE_NAME, csrf_token)
        client.headers.update({CSRF_HEADER_NAME: csrf_token})
        client.headers.update(
            {"Authorization": f"Bearer {create_access_token(data={'sub': user.username, 'jti': 'test'})}"}
        )

        transcript = SqlTranscript()
        listeners = {
            "before_cursor_execute": transcript.statement,
            "begin": transcript.begin,
            "commit": transcript.commit,
            "rollback": transcript.rollback,
        }
        for name, listener in listeners.items():
            event.listen(db_engine.sync_engine, name, listener)
        try:
            response = await client.get(ROUTE)
            transcript.events.append(
                {"event": "request_complete", "status": response.status_code}
            )
        finally:
            for name, listener in listeners.items():
                event.remove(db_engine.sync_engine, name, listener)
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()

    # Every populated section must actually be present. Empty sections would
    # still satisfy the shape check below, so assert the records explicitly.
    assert len(payload["roll_pool"]) >= 8
    assert len(payload["snoozed_threads"]) >= 1
    assert payload["snoozed_count"] >= 1
    assert len(payload["skipped_threads"]) >= 1
    assert len(payload["blocked_threads"]) >= 1
    assert payload["blocked_count"] >= 1
    assert payload["stale_thread_count"] >= 1
    assert payload["stale_thread"] is not None
    assert payload["total_threads"] >= 10
    assert payload["available_threads"] >= 8
    assert any(
        reason["reason"] == "completed"
        for reason in payload["excluded_threads"]
    )
    assert any(
        reason["reason"] == "not_in_queue"
        for reason in payload["inactive_threads"]
    )

    frozen = json.loads(CONTRACT.read_text())
    response_schema = (
        frozen["paths"][ROUTE]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    Draft202012Validator({**response_schema, "components": frozen["components"]}).validate(
        payload
    )
    statements = [row for row in transcript.events if row["event"] == "statement"]
    assert statements
    assert any("threads" in str(row["sql"]) for row in statements)
    assert any("sessions" in str(row["sql"]) for row in statements)
    assert any("tag_assignments" in str(row["sql"]) for row in statements)
    # A real request opens and closes at least one transaction.
    assert any(row["event"] == "begin" for row in transcript.events)
    assert any(row["event"] == "commit" for row in transcript.events)
    assert any(row["event"] == "rollback" for row in transcript.events)
    output = Path(os.environ.get("RUST_SQL_ORACLE_DIR", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / "roll-bootstrap-v1.sql.json").write_text(render({
        "method": "GET", "path": ROUTE,
        "scenario": "synthetic populated library, existing reading session",
        "events": transcript.events,
    }))
