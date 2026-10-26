"""Safety and transactional execution tests for the authorized Torque QA refresh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.ops import refresh_torque_qa_mirror as mirror


def test_sql_manifest_has_scoped_guards_and_parity_verifier() -> None:
    """Every manual refresh includes the audited reader and FK safety checks."""
    statements = mirror.load_statements()
    assert len(statements) >= 49
    assert statements[0] == "SELECT pg_advisory_xact_lock(23199)"
    assert statements[-1].startswith("DO $verify$")
    script = "\n".join(statements)
    assert "crosses reader accounts" in script
    assert "foreign session references QA library" in script
    assert "other reader owns tag assignment to QA records" in script
    assert "selected_thread_id IN" in script
    assert "DELETE FROM users" not in script
    assert "UPDATE users" not in script
    assert "CREATE BRANCH" not in script
    assert "DELETE FROM events WHERE session_id IN" in script
    assert "OR thread_id IN" in script
    assert "WHEN s.next_unread_issue_id IS NULL THEN NULL" in script
    assert "DO $coll$" in script
    assert "pg_temp.qa_rewrite_json" in script


@pytest.mark.parametrize("text", [
    "-- untrusted\n" + mirror.STATEMENT_MARKER + "\nSELECT 1",
    "-- Authorized Torque QA-only\n" + mirror.STATEMENT_MARKER + "\nSELECT 1",
])
def test_sql_manifest_rejects_incomplete_scripts(
    tmp_path: Path, text: str,
) -> None:
    """A truncated SQL file never reaches an apply transaction."""
    path = tmp_path / "bad.sql"
    path.write_text(text)
    with pytest.raises(ValueError, match="incomplete"):
        mirror.load_statements(path)


def mock_engine() -> tuple[MagicMock, AsyncMock]:
    """Provide a connection that captures operations without touching a database."""
    engine = MagicMock()
    connection = AsyncMock()
    engine.connect.return_value.__aenter__.return_value = connection
    engine.begin.return_value.__aenter__.return_value = connection
    connection.execute.return_value.mappings.return_value.one.return_value = {
        "source_threads": 904,
        "qa_threads": 904,
        "source_issues": 7736,
        "qa_issues": 7736,
        "source_lists": 20,
        "qa_lists": 20,
        "source_plans": 18,
        "qa_plans": 18,
    }
    return engine, connection


@pytest.mark.asyncio
async def test_default_run_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default preview never opens a write transaction or executes the SQL."""
    engine, connection = mock_engine()
    monkeypatch.setattr(mirror, "create_async_engine", lambda _: engine)
    await mirror.run(
        apply=False,
        database_url="postgresql+asyncpg://example:secret@localhost/neondb",
    )
    engine.begin.assert_not_called()
    connection.exec_driver_sql.assert_awaited_once_with("SET TRANSACTION READ ONLY")
    connection.rollback.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_runs_every_step_inside_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One commit boundary contains all QA changes and the parity verification."""
    engine, connection = mock_engine()
    monkeypatch.setattr(mirror, "create_async_engine", lambda _: engine)
    statements = mirror.load_statements()
    await mirror.run(
        apply=True,
        database_url="postgresql+asyncpg://example:secret@localhost/neondb",
    )
    engine.begin.assert_called_once()
    actual = [call.args[0] for call in connection.exec_driver_sql.await_args_list]
    assert actual[:3] == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "SET LOCAL lock_timeout = '10s'",
        "SET LOCAL statement_timeout = '180s'",
    ]
    assert actual[3:] == statements + ["SET TRANSACTION READ ONLY"]
    assert connection.execute.await_count == 1
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_error_exits_transaction_with_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An FK failure must not be swallowed or followed by a success report."""
    engine, connection = mock_engine()
    monkeypatch.setattr(mirror, "create_async_engine", lambda _: engine)

    async def fail_on_write(statement: str) -> None:
        if statement.startswith("DELETE FROM threads"):
            raise ValueError("foreign key safety regression")
        return None

    connection.exec_driver_sql.side_effect = fail_on_write
    with pytest.raises(ValueError, match="foreign key safety regression"):
        await mirror.run(
            apply=True,
            database_url="postgresql+asyncpg://example:secret@localhost/neondb",
        )
    engine.begin.return_value.__aexit__.assert_awaited_once()
    exception_type = engine.begin.return_value.__aexit__.await_args.args[0]
    assert exception_type is ValueError
    engine.dispose.assert_awaited_once()
