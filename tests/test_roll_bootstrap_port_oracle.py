"""Record the actual Python v1 bootstrap contract and SQL for its Rust port.

Only fixture-owned synthetic test records are used. This is a reference export,
not a claim that a native implementation matches or serves production traffic.
"""

import json
import os
from pathlib import Path

from httpx import AsyncClient
from jsonschema import Draft202012Validator
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.main import app
from scripts.rust_endpoint_oracle import SqlTranscript, operation_contract, render
from tests.conftest import get_or_create_user_async
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
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """Exercise all v1 library sections and export SQL/binds/transaction ordering."""
    user = await get_or_create_user_async(async_db)
    await _populate_library(async_db, user.id, rollable_count=8)
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
        response = await auth_client.get(ROUTE)
        transcript.events.append({"event": "request_complete", "status": response.status_code})
    finally:
        for name, listener in listeners.items():
            event.remove(db_engine.sync_engine, name, listener)
    assert response.status_code == 200
    frozen = json.loads(CONTRACT.read_text())
    response_schema = (
        frozen["paths"][ROUTE]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    )
    Draft202012Validator({**response_schema, "components": frozen["components"]}).validate(
        response.json()
    )
    statements = [row for row in transcript.events if row["event"] == "statement"]
    assert statements
    assert any("threads" in str(row["sql"]) for row in statements)
    assert any("sessions" in str(row["sql"]) for row in statements)
    assert any("tag_assignments" in str(row["sql"]) for row in statements)
    output = Path(os.environ.get("RUST_SQL_ORACLE_DIR", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    (output / "roll-bootstrap-v1.sql.json").write_text(render({
        "method": "GET", "path": ROUTE,
        "scenario": "synthetic populated library, existing reading session",
        "events": transcript.events,
    }))
