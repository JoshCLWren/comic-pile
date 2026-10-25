"""Database evidence for read-only, owner-scoped shadow loading and reporting."""

from collections.abc import Iterator

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dependency, Issue, Thread, User
from app.models.collection_exclusion import CollectionExclusion
from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.reading_plan_membership import ReadingPlanIssue
from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.services.reading_shadow_service import compare_reading_eligibility
from scripts import report_reading_eligibility
from tests.conftest import get_test_database_url


@pytest.fixture
def statements() -> Iterator[list[str]]:
    """Observe actual SQL so regression cannot hide writes behind service mocks."""
    captured: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        yield captured
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


async def _owner(db: AsyncSession, username: str = "shadow_owner") -> User:
    """Create a local reader for ownership and committed-report fixtures."""
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    return user


async def _series(
    db: AsyncSession, user: User, name: str, count: int
) -> tuple[Thread, list[Issue]]:
    """Seed canonical Issue.position independently of all historical plan copies."""
    thread = Thread(
        user_id=user.id,
        title=name,
        format="Comic",
        status="active",
        queue_position=1,
        issues_remaining=count,
        is_blocked=False,
    )
    db.add(thread)
    await db.flush()
    issues = [
        Issue(thread_id=thread.id, issue_number=str(i + 1), position=i + 1, status="unread")
        for i in range(count)
    ]
    db.add_all(issues)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    return thread, issues


async def test_actual_lists_not_shorter_plan_memberships_drive_snapshot(
    async_db: AsyncSession,
    statements: list[str],
) -> None:
    """Absolute 105/76 and Julix 466/464 retain every authored placement."""
    user = await _owner(async_db)
    for name, count, stale_count in (("Absolute", 105, 76), ("Julix", 466, 464)):
        _, issues = await _series(async_db, user, name, count)
        reading_list = CustomCBLList(user_id=user.id, name=name, mode="loose")
        plan = ContinuityPlan(user_id=user.id, name=name)
        async_db.add_all([reading_list, plan])
        await async_db.flush()
        async_db.add_all(
            [
                CustomCBLEntry(list_id=reading_list.id, issue_id=issue.id, position=p)
                for p, issue in enumerate(issues)
            ]
        )
        async_db.add_all(
            [
                ReadingPlanIssue(
                    plan_id=plan.id,
                    issue_id=issue.id,
                    occurrence_id=f"issue-{issue.id}",
                    lane_id="main",
                    display_position=p,
                )
                for p, issue in enumerate(issues[:stale_count])
            ]
        )
    await async_db.commit()
    statements.clear()
    inputs = await load_shadow_inputs(async_db, user.id)
    assert sorted(len(row.entries) for row in inputs.lists) == [105, 466]
    assert len(inputs.issues) == 571
    assert not inputs.unresolved
    assert len(statements) <= 10  # Fixed query count, not a query per Issue or Thread.
    assert all(
        statement.lstrip().upper().startswith(("SELECT", "SAVEPOINT")) for statement in statements
    )
    result = compare_reading_eligibility(inputs)
    assert result["valid"] is True
    assert not async_db.dirty
    assert not async_db.new
    assert not async_db.deleted


async def test_live_loader_reads_only_reader_dependencies_without_legacy_census(
    async_db: AsyncSession,
) -> None:
    """Live eligibility must not load or count historical dependency rows."""
    user = await _owner(async_db, "live_reader_only")
    _, issues = await _series(async_db, user, "Canonical series", 3)
    async_db.add_all(
        [
            Dependency(
                source_issue_id=issues[0].id,
                target_issue_id=issues[1].id,
                note="cbl-order: historical only",
            ),
            Dependency(
                source_issue_id=issues[0].id,
                target_issue_id=issues[2].id,
                origin="converted",
                classification="C",
                provenance="Historical conversion",
            ),
            Dependency(
                source_issue_id=issues[1].id,
                target_issue_id=issues[2].id,
                origin="reader",
                classification="A",
                provenance="Explicit reader requirement",
            ),
        ]
    )
    await async_db.commit()

    dependency_statements: list[tuple[str, object]] = []

    def capture_binds(conn, cursor, statement, parameters, context, executemany):
        """Capture executed SQL and real DBAPI binds, not formatted query text."""
        if "FROM dependencies" in statement:
            dependency_statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", capture_binds)
    try:
        live = await load_shadow_inputs(
            async_db, user.id, include_legacy_diagnostics=False
        )
    finally:
        event.remove(Engine, "before_cursor_execute", capture_binds)

    assert len(live.prerequisites) == 1
    assert live.prerequisites[0].source_issue_id == issues[1].id
    assert live.prerequisites[0].target_issue_id == issues[2].id
    assert live.inert_dependency_count == 0
    assert len(dependency_statements) == 1
    query, parameters = dependency_statements[0]
    assert "COUNT" not in query.upper()
    assert "WHERE" in query.upper()
    where_clause = query.upper().split("WHERE", 1)[1]
    assert "DEPENDENCIES.ORIGIN =" in where_clause
    bound_values = parameters.values() if isinstance(parameters, dict) else parameters
    assert "reader" in bound_values

    historical = await load_shadow_inputs(async_db, user.id)
    assert len(historical.prerequisites) == 1
    assert historical.inert_dependency_count == 2


async def test_jli_informational_edges_stay_inert_and_local_skip_is_not_exclusion(
    async_db: AsyncSession,
) -> None:
    """No annual inference or old adjacency materialization becomes a prerequisite."""
    user = await _owner(async_db)
    a, a_issues = await _series(async_db, user, "JLI Annual", 1)
    b, b_issues = await _series(async_db, user, "JLE", 1)
    reading_list = CustomCBLList(user_id=user.id, name="JLI/JLE", mode="loose")
    async_db.add(reading_list)
    await async_db.flush()
    async_db.add_all(
        [
            CustomCBLEntry(
                list_id=reading_list.id, issue_id=a_issues[0].id, position=0, skipped=True
            ),
            CustomCBLEntry(list_id=reading_list.id, issue_id=b_issues[0].id, position=1),
            Dependency(
                source_issue_id=a_issues[0].id,
                target_issue_id=b_issues[0].id,
                note="cbl-order: informational JLI placement",
            ),
        ]
    )
    await async_db.commit()
    inputs = await load_shadow_inputs(async_db, user.id)
    assert inputs.inert_dependency_count == 1
    assert inputs.prerequisites == ()
    result = compare_reading_eligibility(inputs)
    rows = result["threads"]
    assert isinstance(rows, list)
    assert {row["thread_id"] for row in rows if row["proposed_eligible"]} == {a.id, b.id}
    assert inputs.excluded_issue_ids == frozenset()
    async_db.add(CollectionExclusion(user_id=user.id, thread_id=a.id))
    await async_db.commit()
    inputs = await load_shadow_inputs(async_db, user.id)
    assert inputs.excluded_issue_ids == frozenset({a_issues[0].id})


async def test_cross_owner_references_are_diagnostic_without_foreign_payload(
    async_db: AsyncSession,
) -> None:
    """A legacy cross-owner edge cannot quietly disappear from shadow validation."""
    user = await _owner(async_db)
    foreign = await _owner(async_db, "private_foreign_username")
    _, own_issues = await _series(async_db, user, "Own", 1)
    _, foreign_issues = await _series(async_db, foreign, "private_foreign_title", 1)
    edge = Dependency(source_issue_id=foreign_issues[0].id, target_issue_id=own_issues[0].id,
                      origin="reader", classification="A", provenance="Invalid cross-owner edge")
    async_db.add(edge)
    await async_db.commit()
    inputs = await load_shadow_inputs(async_db, user.id)
    assert len(inputs.unresolved) == 1
    assert len(inputs.issues) == 1
    result = compare_reading_eligibility(inputs)
    assert result["valid"] is False
    assert "private_foreign" not in str(result)
    assert "unresolved_reference" in str(result)


async def test_cross_owner_historical_edge_cannot_block_a_readers_frontier(
    async_db: AsyncSession,
) -> None:
    """A stale cross-account dependency is neither canonical nor a validation error."""
    user = await _owner(async_db, "historical_own")
    foreign = await _owner(async_db, "historical_foreign")
    own_thread, own_issues = await _series(async_db, user, "Own list", 1)
    _, foreign_issues = await _series(async_db, foreign, "Foreign old copy", 1)
    async_db.add(Dependency(source_issue_id=foreign_issues[0].id,
                            target_issue_id=own_issues[0].id, note="Historical copy"))
    await async_db.commit()
    inputs = await load_shadow_inputs(async_db, user.id)
    assert inputs.prerequisites == ()
    assert not inputs.unresolved
    rows = compare_reading_eligibility(inputs)["threads"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    assert any(row["thread_id"] == own_thread.id and row["proposed_eligible"]
               for row in rows if isinstance(row, dict))


async def test_report_transaction_is_read_only_and_leaves_state_unchanged(
    async_db_committed: AsyncSession,
    statements: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The report reads real storage, and PostgreSQL rejects any attempted mutation."""
    db = async_db_committed
    user = await _owner(db)
    thread, issues = await _series(db, user, "Private reader prose", 2)
    thread.next_unread_issue_id = issues[1].id
    await db.commit()
    before = (await db.execute(select(Thread.next_unread_issue_id, Thread.is_blocked))).all()
    statements.clear()
    result = await report_reading_eligibility.report(get_test_database_url(), user.id)
    assert result["valid"] is True
    assert "Private reader prose" not in str(result)
    assert any("SET TRANSACTION READ ONLY" in statement for statement in statements)
    assert not any(
        statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
        for statement in statements
    )
    assert (
        await db.execute(select(Thread.next_unread_issue_id, Thread.is_blocked))
    ).all() == before

    async def attempt_write(db: AsyncSession, user_id: int, **limits: int) -> dict[str, object]:
        await db.execute(
            text("UPDATE threads SET is_blocked=true WHERE user_id=:uid"), {"uid": user_id}
        )
        return {}

    monkeypatch.setattr(report_reading_eligibility, "shadow_reading_eligibility", attempt_write)
    with pytest.raises(DBAPIError, match="read-only"):
        await report_reading_eligibility.report(get_test_database_url(), user.id)


async def test_all_reader_preflight_is_read_only_and_owner_isolated(
    async_db_committed: AsyncSession,
    statements: list[str],
) -> None:
    """One production-shaped report evaluates every owner in the same read snapshot."""
    db = async_db_committed
    first = await _owner(db, "all_reader_one")
    second = await _owner(db, "all_reader_two")
    one, one_issues = await _series(db, first, "Private one", 1)
    two, two_issues = await _series(db, second, "Private two", 1)
    db.add(Dependency(source_issue_id=one_issues[0].id,
                      target_issue_id=one_issues[0].id, note="Legacy self cycle"))
    await db.commit()
    statements.clear()
    result = await report_reading_eligibility.report_all(get_test_database_url())
    assert result["scope"] == "all_readers"
    assert result["read_only"] is True
    payload = result["reports"]
    assert isinstance(payload, list)
    assert all(isinstance(row, dict) for row in payload)
    reports = {r["user_id"]: r for r in payload if isinstance(r, dict)}
    assert first.id in reports and second.id in reports
    assert reports[first.id]["valid"] is True
    assert reports[second.id]["valid"] is True
    first_rows = reports[first.id]["threads"]
    second_rows = reports[second.id]["threads"]
    assert isinstance(first_rows, list) and isinstance(second_rows, list)
    assert all(isinstance(row, dict) for row in (*first_rows, *second_rows))
    assert one.id in {row["thread_id"] for row in first_rows if isinstance(row, dict)}
    assert two.id not in {row["thread_id"] for row in first_rows if isinstance(row, dict)}
    assert two.id in {row["thread_id"] for row in second_rows if isinstance(row, dict)}
    assert result["readers_valid"] == result["readers_checked"]
    fingerprint = result["source_fingerprint"]
    assert isinstance(fingerprint, str) and len(fingerprint) == 64
    assert any("SET TRANSACTION READ ONLY" in statement for statement in statements)
    assert not any(statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
                   for statement in statements)


async def test_cli_requires_explicit_async_postgres_url() -> None:
    """Diagnostic tooling never falls back to a live URL from application settings."""
    with pytest.raises(ValueError, match="explicit"):
        await report_reading_eligibility.report("sqlite:///ignored", 1)
