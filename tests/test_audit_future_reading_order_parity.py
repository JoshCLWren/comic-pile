"""PostgreSQL coverage for the production future-order parity audit runner.

The pure evaluator tests cover audit_future_parity in isolation. These tests
exercise run() against a real test database and main()'s exit-code contract so
mistakes in the production snapshot load or report are caught.
"""

import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scripts.audit_future_reading_order_parity as audit
from app.models import CollectionExclusion, Dependency, Issue, Thread, User
from tests.conftest import get_test_database_url


TEST_READER_USERNAME = "audit_future_parity_owner"


async def _owner(db: AsyncSession, username: str = TEST_READER_USERNAME) -> User:
    """Create a committed reader visible to the script's separate connection."""
    user = User(
        username=username, password_hash="unused", created_at=datetime.now(UTC)
    )
    db.add(user)
    await db.flush()
    return user


async def _series(
    db: AsyncSession, user: User, title: str, count: int
) -> tuple[Thread, list[Issue]]:
    """Seed a Thread with unread Issues owned by the reader."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        status="active",
        queue_position=1,
        issues_remaining=count,
        is_blocked=False,
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(i + 1),
            position=i + 1,
            status="unread",
        )
        for i in range(count)
    ]
    db.add_all(issues)
    await db.flush()
    return thread, issues


async def test_run_reports_unresolved_historical_edge(
    async_db_committed: AsyncSession,
) -> None:
    """run() exposes a missing future handoff as unresolved with exact IDs."""
    db = async_db_committed
    user = await _owner(db)
    _thread, issues = await _series(db, user, "Frontier series", 2)
    _thread_b, later_issues = await _series(db, user, "Later series", 1)
    source, target = issues[0], later_issues[0]
    db.add(
        Dependency(
            source_issue_id=source.id,
            target_issue_id=target.id,
            origin=None,
            note=None,
            classification=None,
            provenance=None,
        )
    )
    await db.commit()

    before = (
        await db.execute(select(Dependency.id).order_by(Dependency.id))
    ).scalars().all()
    report = await audit.run(get_test_database_url(), user.id)
    after = (
        await db.execute(select(Dependency.id).order_by(Dependency.id))
    ).scalars().all()
    assert before == after  # read-only runner leaves database rows unchanged

    assert report["user_id"] == user.id
    assert report["examined"] == 1
    assert report["implied"] == 0
    assert report["excluded"] == []
    unresolved = report["unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["source"] == source.id
    assert unresolved[0]["target"] == target.id
    assert unresolved[0]["origin"] is None
    assert report["status"] == "REVIEW_REQUIRED"


async def test_run_excludes_edges_with_excluded_endpoint(
    async_db_committed: AsyncSession,
) -> None:
    """run() lists edges with an excluded endpoint under excluded, not missing."""
    db = async_db_committed
    user = await _owner(db)
    _thread, issues = await _series(db, user, "Excluded series", 2)
    source, target = issues[0], issues[1]
    db.add(CollectionExclusion(user_id=user.id, issue_id=target.id))
    db.add(
        Dependency(
            source_issue_id=source.id,
            target_issue_id=target.id,
            origin=None,
            note=None,
            classification=None,
            provenance=None,
        )
    )
    await db.commit()

    report = await audit.run(get_test_database_url(), user.id)

    assert report["examined"] == 1
    assert report["implied"] == 0
    assert report["unresolved"] == []
    assert len(report["excluded"]) == 1
    excluded = report["excluded"][0]
    assert excluded["source"] == source.id
    assert excluded["target"] == target.id
    assert "excluded from reading history" in excluded["reason"]
    assert report["status"] == "PASS"


async def test_run_filters_non_historical_inert_and_read_edges(
    async_db_committed: AsyncSession,
) -> None:
    """The production SQL audits only unread, non-reader, non-inert edges."""
    db = async_db_committed
    user = await _owner(db)
    _thread, issues = await _series(db, user, "Audited series", 3)
    _later_thread, later_issues = await _series(db, user, "Later series", 2)
    source = issues[0]
    read_target = issues[1]
    read_target.status = "read"
    audited = Dependency(
        source_issue_id=source.id,
        target_issue_id=later_issues[0].id,
        origin=None,
        note=None,
        classification=None,
        provenance=None,
    )
    db.add_all([
        audited,
        # Reader-approved prerequisites belong to the live graph, not this audit.
        Dependency(
            source_issue_id=source.id,
            target_issue_id=later_issues[1].id,
            origin="reader",
            note=None,
            classification=None,
            provenance=None,
        ),
        # Inert generated adjacency is not a historical requirement.
        Dependency(
            source_issue_id=issues[2].id,
            target_issue_id=later_issues[1].id,
            origin=None,
            note="cbl-order:123",
            classification=None,
            provenance=None,
        ),
        # Already-read targets are not future order.
        Dependency(
            source_issue_id=source.id,
            target_issue_id=read_target.id,
            origin=None,
            note=None,
            classification=None,
            provenance=None,
        ),
    ])
    await db.commit()

    report = await audit.run(get_test_database_url(), user.id)

    assert report["examined"] == 1
    assert report["implied"] == 0
    assert [edge["id"] for edge in report["unresolved"]] == [audited.id]
    assert report["status"] == "REVIEW_REQUIRED"


def test_main_exit_code_review_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() exits nonzero when the audit requires review."""
    calls: list[tuple[str, int]] = []

    async def fake_run(url: str, uid: int) -> dict:
        calls.append((url, uid))
        return {"status": "REVIEW_REQUIRED"}

    monkeypatch.setattr(audit, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_future_reading_order_parity.py",
            "--database-url",
            "postgresql+asyncpg://localhost/test",
            "--user-id",
            "7",
        ],
    )
    assert audit.main() == 1
    assert calls == [("postgresql+asyncpg://localhost/test", 7)]


def test_main_exit_code_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main() exits zero when the audit passes."""

    async def fake_run(url: str, uid: int) -> dict:
        return {"status": "PASS"}

    monkeypatch.setattr(audit, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_future_reading_order_parity.py",
            "--database-url",
            "postgresql+asyncpg://localhost/test",
            "--user-id",
            "7",
        ],
    )
    assert audit.main() == 0


async def test_run_marks_reversed_compiled_sequence(
    async_db_committed: AsyncSession,
) -> None:
    """A legacy rule reversed against the natural order is not an unmet gate."""
    db = async_db_committed
    user = await _owner(db)
    _thread, issues = await _series(db, user, "Old reverse series", 2)
    old = Dependency(
        source_issue_id=issues[1].id,
        target_issue_id=issues[0].id,
        origin="converted",
        classification="C",
        provenance="old compiled rule",
    )
    db.add(old)
    await db.commit()
    report = await audit.run(get_test_database_url(), user.id)
    assert report["examined"] == 1
    assert report["implied"] == 0
    assert report["unresolved"] == []
    assert len(report["contradicted"]) == 1
    assert report["contradicted"][0]["id"] == old.id
    assert report["status"] == "REVIEW_REQUIRED"
