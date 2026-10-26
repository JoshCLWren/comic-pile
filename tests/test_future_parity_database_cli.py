"""Database and CLI regressions for future-order parity reporting."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from scripts import audit_future_reading_order_parity as cli
from tests.conftest import get_test_database_url


async def test_read_only_cli_identifies_unprotected_handoff(
    async_db_committed: AsyncSession,
) -> None:
    """Exercise real SQL filtering and verify no historical row is mutated."""
    user = User(username="future_parity_cli", password_hash="unused")
    async_db_committed.add(user)
    await async_db_committed.flush()
    first = Thread(
        user_id=user.id, title="Before", format="Comic",
        status="active", queue_position=1, is_blocked=False,
    )
    second = Thread(
        user_id=user.id, title="After", format="Comic",
        status="active", queue_position=2, is_blocked=False,
    )
    async_db_committed.add_all([first, second])
    await async_db_committed.flush()
    source = Issue(
        thread_id=first.id, issue_number="1", position=1, status="unread",
    )
    target = Issue(
        thread_id=second.id, issue_number="1", position=1, status="unread",
    )
    async_db_committed.add_all([source, target])
    await async_db_committed.flush()
    old = Dependency(
        source_issue_id=source.id, target_issue_id=target.id,
        note="Documented crossover", origin=None,
    )
    async_db_committed.add(old)
    await async_db_committed.commit()
    report = await cli.run(get_test_database_url(), user.id)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["examined"] == 1
    assert report["implied"] == 0
    assert report["excluded"] == []
    assert report["unresolved"][0]["id"] == old.id
    assert report["unresolved"][0]["source_label"] == "Before #1"
    assert report["unresolved"][0]["target_label"] == "After #1"
    stored = await async_db_committed.scalar(
        select(Dependency).where(Dependency.id == old.id)
    )
    assert stored is not None
    assert stored.origin is None
    assert stored.note == "Documented crossover"
    assert await async_db_committed.scalar(
        select(Issue.status).where(Issue.id == target.id)
    ) == "unread"


@pytest.mark.parametrize("status,code", [
    ("REVIEW_REQUIRED", 1),
    ("PASS", 0),
])
def test_main_returns_report_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: str,
    code: int,
) -> None:
    """Check JSON output and process exit policy without a remote database."""
    async def fake_run(url: str, uid: int) -> dict[str, object]:
        """Return a tiny deterministic audit result."""
        assert url == "postgresql+asyncpg://example/test"
        assert uid == 17
        return {"status": status, "unresolved": []}

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(
        sys, "argv", [
            "audit_future_reading_order_parity",
            "--database-url", "postgresql+asyncpg://example/test",
            "--user-id", "17",
        ],
    )
    assert cli.main() == code
    parsed: Mapping[str, object] = json.loads(capsys.readouterr().out)
    assert parsed["status"] == status
