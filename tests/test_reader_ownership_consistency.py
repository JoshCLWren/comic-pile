"""Reader-ownership consistency at graph and library write boundaries (#3225).

Three layers are proven here:

* the PostgreSQL ownership triggers reject invalid direct SQL inserts and
  updates (the database boundary);
* the centralized service validators reject the same edges through the central
  write paths, including when two readers share one ``CatalogIssue``;
* the read-only preflight report finds existing violations and never selects
  private reader payloads.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import (
    CatalogIssue,
    ContinuityPlan,
    Dependency,
    ExternalIdentity,
    Issue,
    ReadingSession,
    Tag,
    TagAssignment,
    Thread,
    User,
)
from app.repositories import ownership_consistency_repository
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services import dependency_service, ownership_consistency
from app.services.reading_plan_normalization import rebuild_plan_membership

PASSWORD_HASH = hash_password("password")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

MIGRATION_PATH = (
    REPOSITORY_ROOT
    / "alembic"
    / "versions"
    / "m5d400000001_enforce_reader_ownership_consistency.py"
)
MANIFEST_PATH = REPOSITORY_ROOT / "alembic" / "preflight" / "m5d400000001.json"


async def _make_user(db: AsyncSession, username: str) -> User:
    """Create and flush a throwaway reader."""
    user = User(username=username, password_hash=PASSWORD_HASH)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_thread(db: AsyncSession, user_id: int, title: str) -> Thread:
    """Create and flush an active thread owned by ``user_id``."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        user_id=user_id,
        status="active",
    )
    db.add(thread)
    await db.flush()
    await db.refresh(thread)
    return thread


async def _make_issue(
    db: AsyncSession,
    thread_id: int,
    issue_number: str,
    position: int,
    *,
    catalog_issue_id: int | None = None,
) -> Issue:
    """Create and flush one unread issue inside ``thread_id``."""
    issue = Issue(
        thread_id=thread_id,
        issue_number=issue_number,
        position=position,
        status="unread",
        catalog_issue_id=catalog_issue_id,
    )
    db.add(issue)
    await db.flush()
    await db.refresh(issue)
    return issue


async def _connection_can_bypass_triggers(db: AsyncSession) -> bool:
    """Return whether this connection may temporarily bypass triggers.

    Simulating a pre-existing violation requires writing a row the new
    constraints reject. ``session_replication_role`` is the session-local,
    cross-worker-safe way to do that, and only a superuser may set it.
    """
    result = await db.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    )
    return bool(result.scalar())


@pytest_asyncio.fixture
async def reader_a(db: AsyncSession) -> User:
    """First reader used for cross-reader ownership assertions."""
    return await _make_user(db, "ownership_reader_a")


@pytest_asyncio.fixture
async def reader_b(db: AsyncSession) -> User:
    """Second reader used for cross-reader ownership assertions."""
    return await _make_user(db, "ownership_reader_b")


@pytest_asyncio.fixture
async def shared_catalog_issue(db: AsyncSession) -> CatalogIssue:
    """One CatalogIssue both readers' issues point at.

    Shared catalog identity must never become authorization evidence: two
    readers legitimately reference the same catalog row.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="catalog-shared-3225",
        external_url="https://example.invalid/issue/3225",
        metadata_json={"name": "Shared Issue #1"},
    )
    db.add(identity)
    await db.flush()
    catalog_issue = CatalogIssue(canonical_external_identity_id=identity.id)
    db.add(catalog_issue)
    await db.flush()
    await db.refresh(catalog_issue)
    return catalog_issue


@pytest_asyncio.fixture
async def shared_catalog_threads(
    db: AsyncSession, reader_a: User, reader_b: User, shared_catalog_issue: CatalogIssue
) -> tuple[Thread, Thread, Issue, Issue]:
    """Two readers' threads whose issues share one CatalogIssue."""
    thread_a = await _make_thread(db, reader_a.id, "Reader A Shared")
    thread_b = await _make_thread(db, reader_b.id, "Reader B Shared")
    issue_a = await _make_issue(db, thread_a.id, "1", 1, catalog_issue_id=shared_catalog_issue.id)
    issue_b = await _make_issue(db, thread_b.id, "1", 1, catalog_issue_id=shared_catalog_issue.id)
    return thread_a, thread_b, issue_a, issue_b


@pytest.mark.asyncio
async def test_direct_sql_cannot_point_frontier_at_another_threads_issue(
    db: AsyncSession, reader_a: User, shared_catalog_threads: tuple[Thread, Thread, Issue, Issue]
) -> None:
    """A same-reader wrong-thread frontier is rejected by the database."""
    thread_a, _thread_b, issue_a, _issue_b = shared_catalog_threads
    thread_a.next_unread_issue_id = issue_a.id
    await db.commit()

    # Same reader, different thread, same shared catalog identity: still invalid.
    sibling_thread = await _make_thread(db, reader_a.id, "Reader A Sibling")
    sibling_issue = await _make_issue(db, sibling_thread.id, "1", 1)
    await db.commit()

    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE threads SET next_unread_issue_id = :issue_id WHERE id = :thread_id"),
            {"issue_id": sibling_issue.id, "thread_id": thread_a.id},
        )


@pytest.mark.asyncio
async def test_direct_sql_cannot_point_frontier_at_another_readers_issue(
    db: AsyncSession, shared_catalog_threads: tuple[Thread, Thread, Issue, Issue]
) -> None:
    """A cross-reader frontier is rejected even when the catalog row is shared."""
    thread_a, _thread_b, _issue_a, issue_b = shared_catalog_threads

    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE threads SET next_unread_issue_id = :issue_id WHERE id = :thread_id"),
            {"issue_id": issue_b.id, "thread_id": thread_a.id},
        )


@pytest.mark.asyncio
async def test_direct_sql_thread_insert_cannot_smuggle_a_foreign_frontier(
    db: AsyncSession, reader_a: User, reader_b: User
) -> None:
    """A brand-new thread cannot be inserted with another reader's frontier."""
    foreign_thread = await _make_thread(db, reader_b.id, "Reader B Source")
    foreign_issue = await _make_issue(db, foreign_thread.id, "1", 1)
    await db.commit()

    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO threads (title, format, issues_remaining, queue_position, status,"
                " user_id, manual_creator_credits, is_test, is_blocked, created_at,"
                " next_unread_issue_id)"
                " VALUES ('Smuggled', 'Comic', 0, 9, 'active', :user_id, '[]'::json, false,"
                " false, now(), :issue_id)"
            ),
            {"user_id": reader_a.id, "issue_id": foreign_issue.id},
        )


@pytest.mark.asyncio
async def test_direct_sql_cannot_point_a_session_at_another_readers_thread(
    db: AsyncSession, reader_a: User, reader_b: User
) -> None:
    """A reading session may not pin another reader's pending thread."""
    foreign_thread = await _make_thread(db, reader_b.id, "Reader B Pending")
    db.add(ReadingSession(user_id=reader_a.id))
    await db.commit()

    with pytest.raises(IntegrityError):
        await db.execute(
            text("UPDATE sessions SET pending_thread_id = :thread_id WHERE user_id = :user_id"),
            {"thread_id": foreign_thread.id, "user_id": reader_a.id},
        )


@pytest.mark.asyncio
async def test_direct_sql_session_insert_cannot_smuggle_a_foreign_pending_thread(
    db: AsyncSession, reader_a: User, reader_b: User
) -> None:
    """A brand-new reading session cannot be inserted with a foreign pending thread."""
    foreign_thread = await _make_thread(db, reader_b.id, "Reader B New Session")
    await db.commit()

    with pytest.raises(IntegrityError):
        await db.execute(
            text(
                "INSERT INTO sessions (user_id, pending_thread_id, start_die, reading_mode_suggested,"
                " started_at) VALUES (:user_id, :thread_id, 6, false, now())"
            ),
            {"user_id": reader_a.id, "thread_id": foreign_thread.id},
        )


@pytest.mark.asyncio
async def test_own_frontier_and_pending_references_are_accepted(
    db: AsyncSession, reader_a: User
) -> None:
    """The constraints never block the reader's own valid edges."""
    thread = await _make_thread(db, reader_a.id, "Reader A Own")
    issue = await _make_issue(db, thread.id, "1", 1)
    await db.commit()

    thread.next_unread_issue_id = issue.id
    db.add(ReadingSession(user_id=reader_a.id, pending_thread_id=thread.id))
    await db.commit()

    await db.refresh(thread)
    assert thread.next_unread_issue_id == issue.id


@pytest.mark.asyncio
async def test_deleting_a_frontier_issue_still_clears_the_reference(
    db: AsyncSession, reader_a: User
) -> None:
    """Ownership enforcement must not break the existing ON DELETE SET NULL path."""
    thread = await _make_thread(db, reader_a.id, "Reader A Delete")
    issue = await _make_issue(db, thread.id, "1", 1)
    thread.next_unread_issue_id = issue.id
    await db.commit()

    await db.delete(issue)
    await db.commit()

    await db.refresh(thread)
    assert thread.next_unread_issue_id is None


@pytest.mark.asyncio
async def test_shared_catalog_access_grants_nothing_beyond_the_catalog_row(
    db: AsyncSession, shared_catalog_threads: tuple[Thread, Thread, Issue, Issue]
) -> None:
    """A shared CatalogIssue is identity evidence, never authorization evidence."""
    thread_a, thread_b, issue_a, issue_b = shared_catalog_threads
    private_tag = Tag(
        name="Reader B Only",
        normalized_name="reader b only",
        scope="private",
        owner_user_id=thread_b.user_id,
        color="#112233",
    )
    db.add(private_tag)
    await db.flush()
    db.add(TagAssignment(tag_id=private_tag.id, target_type="Thread", target_id=thread_b.id))
    await db.commit()

    report = await ownership_consistency.reader_ownership_violation_report(db)
    assert report["thread_frontier_outside_thread"]["count"] == 0
    assert report["session_pending_thread_other_reader"]["count"] == 0

    # Both readers own an Issue row for the same CatalogIssue; neither thread can
    # legally adopt the other's issue.
    assert issue_a.catalog_issue_id == issue_b.catalog_issue_id

    escaped = await ownership_consistency_repository.find_issue_ids_outside_thread(
        db, thread_id=thread_a.id, issue_ids=[issue_b.id]
    )
    assert escaped == {issue_b.id}

    unowned = await ownership_consistency_repository.find_unowned_issue_ids(
        db, user_id=thread_a.user_id, issue_ids=[issue_a.id, issue_b.id]
    )
    assert unowned == {issue_b.id}


@pytest.mark.asyncio
async def test_dependency_rejects_another_readers_issue_with_shared_catalog(
    auth_client: AsyncClient,
    db: AsyncSession,
    default_user: User,
    reader_b: User,
    shared_catalog_issue: CatalogIssue,
) -> None:
    """The graph write boundary rejects a foreign issue even with one shared CatalogIssue.

    The API reports another reader's issue exactly like a missing one, so the
    Dependency endpoint cannot be used as an existence oracle, and the central
    service path applies the identical rejection without writing a row.
    """
    own_thread = await _make_thread(db, default_user.id, "Reader Own Graph")
    foreign_thread = await _make_thread(db, reader_b.id, "Reader B Graph")
    own_issue = await _make_issue(
        db, own_thread.id, "1", 1, catalog_issue_id=shared_catalog_issue.id
    )
    foreign_issue = await _make_issue(
        db, foreign_thread.id, "1", 1, catalog_issue_id=shared_catalog_issue.id
    )
    await db.commit()
    assert own_issue.catalog_issue_id == foreign_issue.catalog_issue_id

    foreign = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": own_issue.id,
            "target_type": "issue",
            "target_id": foreign_issue.id,
        },
    )
    missing = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": own_issue.id,
            "target_type": "issue",
            "target_id": 987654321,
        },
    )
    assert foreign.status_code == 404
    assert missing.status_code == 404
    assert foreign.json() == missing.json()

    result, warning = await dependency_service.create_dependency(
        own_issue.id, foreign_issue.id, default_user.id, db
    )
    assert result is None
    assert warning == "Issue not found"

    stored = await db.execute(
        select(Dependency)
        .where(Dependency.source_issue_id == own_issue.id)
        .where(Dependency.target_issue_id == foreign_issue.id)
    )
    assert stored.scalar_one_or_none() is None


def test_ownership_constraints_imports_before_app_models() -> None:
    """``app.ownership_constraints`` stays importable before ``app.models``.

    ``app.models.__init__`` calls ``install_reader_ownership_constraints`` while
    the package is still initializing, so a module-scope model import in this
    module would make any first-touch import of it fail with a circular-import
    error instead of registering the DDL.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import app.ownership_constraints"],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_plan_membership_rejects_another_readers_issue(
    db: AsyncSession, reader_a: User, shared_catalog_threads: tuple[Thread, Thread, Issue, Issue]
) -> None:
    """Plan membership is a write boundary: cross-reader issues are rejected."""
    _thread_a, _thread_b, _issue_a, issue_b = shared_catalog_threads
    plan = ContinuityPlan(user_id=reader_a.id, name="Reader A Plan", nodes_json=[], lanes_json=[])
    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    node = ContinuityPlanNode(
        id="node-1", node_type="issue", ref_id=issue_b.id, lane_id="lane-1", position=1
    )

    with pytest.raises(HTTPException) as excinfo:
        await rebuild_plan_membership(db, plan_id=plan.id, nodes=[node])

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "unowned_plan_issue"
    assert excinfo.value.detail["issue_ids"] == [issue_b.id]


@pytest.mark.asyncio
async def test_plan_membership_rejects_a_missing_issue_without_revealing_it(
    db: AsyncSession, reader_a: User
) -> None:
    """A missing issue is rejected exactly like another reader's issue."""
    plan = ContinuityPlan(
        user_id=reader_a.id, name="Reader A Missing", nodes_json=[], lanes_json=[]
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    node = ContinuityPlanNode(
        id="node-1", node_type="issue", ref_id=987654, lane_id="lane-1", position=1
    )

    with pytest.raises(HTTPException) as excinfo:
        await rebuild_plan_membership(db, plan_id=plan.id, nodes=[node])

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == {"code": "unowned_plan_issue", "issue_ids": [987654]}


@pytest.mark.asyncio
async def test_plan_membership_accepts_the_plan_readers_own_issue(
    db: AsyncSession, reader_a: User, shared_catalog_threads: tuple[Thread, Thread, Issue, Issue]
) -> None:
    """The gate never blocks the plan reader's own membership."""
    _thread_a, _thread_b, issue_a, _issue_b = shared_catalog_threads
    plan = ContinuityPlan(
        user_id=reader_a.id, name="Reader A Own Plan", nodes_json=[], lanes_json=[]
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    node = ContinuityPlanNode(
        id="node-1", node_type="issue", ref_id=issue_a.id, lane_id="lane-1", position=1
    )
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=[node])
    await db.commit()

    rows = (
        await db.execute(
            text("SELECT issue_id FROM reading_plan_issues WHERE plan_id = :plan_id"),
            {"plan_id": plan.id},
        )
    ).all()
    assert [int(row[0]) for row in rows] == [issue_a.id]


@pytest.mark.asyncio
async def test_plan_membership_with_no_issue_nodes_is_a_no_op(
    db: AsyncSession, reader_a: User
) -> None:
    """Plans with only thread/crossover nodes skip the ownership gate entirely."""
    plan = ContinuityPlan(
        user_id=reader_a.id, name="Reader A Thread Only", nodes_json=[], lanes_json=[]
    )
    db.add(plan)
    await db.flush()
    await db.refresh(plan)

    node = ContinuityPlanNode(
        id="node-1", node_type="thread", ref_id=999, lane_id="lane-1", position=1
    )
    await rebuild_plan_membership(db, plan_id=plan.id, nodes=[node])
    await db.commit()

    rows = (
        await db.execute(
            text("SELECT count(*) FROM reading_plan_issues WHERE plan_id = :plan_id"),
            {"plan_id": plan.id},
        )
    ).scalar()
    assert int(rows or 0) == 0


@pytest.mark.asyncio
async def test_preflight_report_finds_violations_without_private_payloads(
    db: AsyncSession, reader_a: User, reader_b: User
) -> None:
    """The preflight report is bounded and carries no reader content."""
    if not await _connection_can_bypass_triggers(db):
        pytest.skip("connection may not bypass triggers to simulate a legacy row")

    thread_a = await _make_thread(db, reader_a.id, "Reader A Frontier")
    _thread_b = await _make_thread(db, reader_b.id, "Reader B Pending")
    await db.execute(
        text("UPDATE threads SET notes = :notes WHERE id = :thread_id"),
        {"notes": "TOP SECRET READER NOTE", "thread_id": thread_a.id},
    )
    await db.commit()

    # Simulate a pre-existing invalid row the way a legacy write would have.
    await db.execute(text("SET session_replication_role = replica"))
    try:
        session_b = ReadingSession(user_id=reader_b.id, pending_thread_id=thread_a.id)
        db.add(session_b)
        await db.commit()
    finally:
        await db.execute(text("SET session_replication_role = origin"))

    report = await ownership_consistency.reader_ownership_violation_report(db, limit=5)

    assert report["session_pending_thread_other_reader"]["count"] == 1
    section_row = report["session_pending_thread_other_reader"]["rows"][0]
    assert section_row[0] == session_b.id
    assert section_row[1] == reader_b.id
    assert section_row[2] == thread_a.id
    assert section_row[3] == reader_a.id

    serialized = json.dumps(report, default=str)
    assert "TOP SECRET READER NOTE" not in serialized
    assert "Reader B Pending" not in serialized
    assert "Reader A Frontier" not in serialized


@pytest.mark.asyncio
async def test_preflight_report_is_clean_for_a_healthy_database(
    db: AsyncSession, reader_a: User
) -> None:
    """A healthy database reports zero rows for every violation class."""
    thread = await _make_thread(db, reader_a.id, "Reader A Healthy")
    issue = await _make_issue(db, thread.id, "1", 1)
    thread.next_unread_issue_id = issue.id
    db.add(ReadingSession(user_id=reader_a.id, pending_thread_id=thread.id))
    await db.commit()

    report = await ownership_consistency.reader_ownership_violation_report(db)
    assert report["thread_frontier_outside_thread"] == {"count": 0, "rows": []}
    assert report["session_pending_thread_other_reader"] == {"count": 0, "rows": []}


def test_preflight_manifest_is_valid_and_payload_free() -> None:
    """The machine-enforced production preflight manifest stays read-only."""
    from scripts import migration_safety as ms

    manifest = ms.load_manifest(MANIFEST_PATH)
    assert manifest.revision == "m5d400000001"
    assert len(manifest.preflight_checks) == 2
    for check in manifest.preflight_checks:
        ms.require_select_only(check.sql)
        assert "notes" not in check.sql
        assert "title" not in check.sql


def test_migration_installs_exactly_the_model_level_triggers() -> None:
    """The migration and ``create_all`` install identical enforcement."""
    from app import ownership_constraints

    migration_source = MIGRATION_PATH.read_text(encoding="utf-8")
    for statements in (
        ownership_constraints.THREAD_FRONTIER_TRIGGER_STATEMENTS,
        ownership_constraints.SESSION_PENDING_TRIGGER_STATEMENTS,
    ):
        for statement in statements:
            assert statement.strip() in migration_source
    assert ownership_constraints.THREAD_FRONTIER_TRIGGER_NAME in migration_source
    assert ownership_constraints.SESSION_PENDING_TRIGGER_NAME in migration_source


def test_each_installed_statement_is_a_single_sql_statement() -> None:
    """One statement per execute keeps asyncpg's simple query protocol usable.

    Semicolons are only ever legal inside the dollar-quoted plpgsql body; a
    stray top-level ``;`` would make the driver split the string into a
    multi-statement command, which asyncpg refuses.
    """
    from app import ownership_constraints

    for statements in (
        ownership_constraints.THREAD_FRONTIER_TRIGGER_STATEMENTS,
        ownership_constraints.SESSION_PENDING_TRIGGER_STATEMENTS,
    ):
        for statement in statements:
            body = re.sub(r"\$cp\$.*?\$cp\$", "", statement, flags=re.DOTALL)
            body = body.strip().rstrip(";").strip()
            assert ";" not in body
            assert body.split(maxsplit=1)[0].upper() in {"CREATE", "DROP"}