"""Tests for the #2553 canonical Dependency backfill migration (c25530000001).

The migration persists one canonical Dependency edge per rule-native
ContinuityRule (item_read directly, converged expanded per prerequisite),
links edges to their owning Reading Plans with ownership validation, and
aborts on genuinely invalid rows (cycles, cross-user issues, non-issue
endpoints). A reviewed allowlist of six test-user ContinuityRule ids may
dangle: those rows are reported and left unchanged. Any other dangling
rule aborts with an investigation-grade error.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.thread import Thread
from app.models.user import User
from app.services import canonical_backfill as mig
from app.services.canonical_constraint_compiler import (
    BACKFILL_EDGE_NOTE_PREFIX,
    EDGE_NOTE_PREFIX,
)
from comic_pile.dependencies import _get_blocked_thread_ids_uncached

_PROD_MISSING_ISSUES = (1117318, 1117522, 1117685)
_ALLOWLISTED_RULE_IDS = tuple(
    sorted(rule_id for rule_id, _owner in mig.DANGLING_RULE_ALLOWLIST)
)


def _sync_connection() -> sa.Connection:
    """Open a sync psycopg connection to the test database for migration calls."""
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql+psycopg")
    engine = sa.create_engine(url)
    return engine.connect()


async def _user(db: AsyncSession, username: str) -> User:
    user = User(username=username, created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


async def _reviewed_dangling_owner(db: AsyncSession) -> User:
    """Return the reviewed test user (id 23199), creating it when absent."""
    existing = await db.get(User, mig.REVIEWED_DANGLING_OWNER_USER_ID)
    if existing is not None:
        return existing
    user = User(
        id=mig.REVIEWED_DANGLING_OWNER_USER_ID,
        username=f"reviewed-dangling-owner-{mig.REVIEWED_DANGLING_OWNER_USER_ID}",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()
    return user


def _allowlisted_dangling_specs(
    surviving_source_id: int, surviving_target_id: int
) -> list[tuple[int, int, int]]:
    """Return (rule_id, source_id, target_id) for the six reviewed prod rows."""
    missing_a, missing_b, missing_c = _PROD_MISSING_ISSUES
    return [
        (_ALLOWLISTED_RULE_IDS[0], missing_a, surviving_target_id),
        (_ALLOWLISTED_RULE_IDS[1], surviving_source_id, missing_b),
        (_ALLOWLISTED_RULE_IDS[2], missing_c, surviving_target_id),
        (_ALLOWLISTED_RULE_IDS[3], surviving_source_id, missing_c),
        (_ALLOWLISTED_RULE_IDS[4], missing_a, missing_b),
        (_ALLOWLISTED_RULE_IDS[5], missing_b, missing_c),
    ]


async def _thread_with_issues(
    db: AsyncSession, user_id: int, title: str, numbers: list[str]
) -> tuple[Thread, list[Issue]]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=1,
        status="active",
        total_issues=len(numbers),
        issues_remaining=len(numbers),
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position, number in enumerate(numbers, start=1):
        issue = Issue(thread_id=thread.id, issue_number=number, position=position, status="unread")
        db.add(issue)
        issues.append(issue)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


async def _plan(db: AsyncSession, user_id: int, name: str) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
    )
    db.add(plan)
    await db.flush()
    return plan


async def _clean(db: AsyncSession) -> None:
    for model in (ReadingPlanDependency, ContinuityRule, Dependency, ContinuityPlan):
        await db.execute(sa.delete(model))
    await db.commit()


@pytest.fixture
async def _isolated_migration_data(async_db_committed: AsyncSession):
    """Provide a committed session and clean migration tables before and after."""
    await _clean(async_db_committed)
    try:
        yield async_db_committed
    finally:
        await _clean(async_db_committed)


@pytest.mark.asyncio
async def test_backfill_creates_edges_and_validated_plan_links(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Rule-native rules become edges; plan links require same-user ownership."""
    db = _isolated_migration_data

    user1 = await _user(db, "cutover-user-1")
    user2 = await _user(db, "cutover-user-2")
    plan1 = await _plan(db, user1.id, "User 1 Plan")
    plan2 = await _plan(db, user2.id, "User 2 Plan")
    _, (a1, a2) = await _thread_with_issues(db, user1.id, "Alpha", ["1", "2"])
    _, (b1, b2) = await _thread_with_issues(db, user1.id, "Beta", ["1", "2"])
    _, (c1, c2) = await _thread_with_issues(db, user2.id, "Gamma", ["1", "2"])

    # Existing edge + mirror rule: the edge already exists, so the rule is skipped.
    existing = Dependency(source_issue_id=a1.id, target_issue_id=a2.id, note="existing")
    db.add(existing)
    await db.flush()

    db.add_all(
        [
            # Plan-owned item_read -> edge + plan link.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=b1.id,
                satisfaction_type="item_read",
                note=f"continuity-plan:{plan1.id}",
            ),
            # Standalone item_read -> edge, no plan link.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a2.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="item_read",
            ),
            # Mirror of an existing edge -> skipped entirely.
            ContinuityRule(
                user_id=user1.id,
                legacy_dependency_id=existing.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=a2.id,
                satisfaction_type="item_read",
            ),
            # Converged rule -> one edge per prerequisite; both duplicates
            # already exist from the item_read rules above, so nothing new,
            # but both get plan links.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=b2.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="converged",
                convergence_targets=[
                    {"type": "issue", "id": a1.id},
                    {"type": "issue", "id": a2.id},
                ],
                note=f"continuity-plan:{plan1.id}",
            ),
            # Converged rule listing its own target -> self-edge skipped.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=b1.id,
                target_type="issue",
                target_id=b1.id,
                satisfaction_type="converged",
                convergence_targets=[
                    {"type": "issue", "id": b1.id},
                    {"type": "issue", "id": a2.id},
                ],
            ),
            # Cross-user plan note -> edge created, plan link skipped.
            ContinuityRule(
                user_id=user2.id,
                source_type="issue",
                source_id=c1.id,
                target_type="issue",
                target_id=c2.id,
                satisfaction_type="item_read",
                note=f"continuity-plan:{plan1.id}",
            ),
            # Dangling plan note -> edge created, plan link skipped.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="item_read",
                note="continuity-plan:999999",
            ),
        ]
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        mig.drop_mirror_trigger(conn)
        item_inserted, _ = mig.backfill_item_read_edges(conn)
        conv_inserted, _, conv_self = mig.backfill_converged_edges(conn)
        links_created, links_skipped = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    # item_read: r1 (a1->b1), r2 (a2->b2), r6 (c1->c2), r7 (a1->b2) = 4 new edges.
    assert item_inserted == 4
    # Converged: both of r4's edges already exist (duplicates of item_read
    # edges); r5 contributes a2->b1, and the b1->b1 self-edge is skipped.
    assert conv_inserted == 1
    assert conv_self == 1

    edges = {
        (source_issue_id, target_issue_id): note
        for source_issue_id, target_issue_id, note in await db.execute(
            sa.select(Dependency.source_issue_id, Dependency.target_issue_id, Dependency.note)
        )
    }
    assert (edges[(a1.id, b1.id)] or "").startswith(BACKFILL_EDGE_NOTE_PREFIX)
    assert (edges[(c1.id, c2.id)] or "").startswith(BACKFILL_EDGE_NOTE_PREFIX)
    assert (b1.id, b1.id) not in edges  # self-edge never persisted

    links = {
        (plan_id, dependency_id)
        for plan_id, dependency_id in await db.execute(
            sa.select(ReadingPlanDependency.plan_id, ReadingPlanDependency.dependency_id)
        )
    }
    edge_ids = {
        (s, t): dep_id
        for dep_id, s, t in await db.execute(
            sa.select(Dependency.id, Dependency.source_issue_id, Dependency.target_issue_id)
        )
    }
    # Plan-owned rules link their edges to the owning plan.
    assert (plan1.id, edge_ids[(a1.id, b1.id)]) in links
    assert (plan1.id, edge_ids[(a1.id, b2.id)]) in links
    assert (plan1.id, edge_ids[(a2.id, b2.id)]) in links
    # The converged rule without a plan note creates an edge but no link.
    assert (plan1.id, edge_ids[(a2.id, b1.id)]) not in links
    # Cross-user and dangling plan notes never produce links.
    assert (plan1.id, edge_ids[(c1.id, c2.id)]) not in links
    assert (plan2.id, edge_ids[(c1.id, c2.id)]) not in links
    assert links_created == 3
    assert len(links_skipped) == 2

    # Mirror rule left no trace: no new edge, no link for the existing one.
    assert edges[(a1.id, a2.id)] == "existing"


@pytest.mark.asyncio
async def test_backfill_skips_allowlisted_dangling_rules_and_reports_them(
    _isolated_migration_data: AsyncSession,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reviewed test-user dangling rules skip, report, and stay unchanged.

    Production deploy of c25530000001 aborted on six ContinuityRules owned
    by test user 23199. Those exact (rule_id, user_id) pairs may skip; every
    skip must name the owner, rule, missing issue ids, and missing side.
    """
    db = _isolated_migration_data

    user = await _reviewed_dangling_owner(db)
    plan = await _plan(db, user.id, "Dangling Owner Plan")
    source_thread, (valid_source,) = await _thread_with_issues(
        db, user.id, "Delta Source", ["1"]
    )
    target_thread, (valid_target,) = await _thread_with_issues(
        db, user.id, "Delta Target", ["1"]
    )
    dangling_target_thread, (surviving_target,) = await _thread_with_issues(
        db, user.id, "Delta Dangling Target", ["1"]
    )
    dangling_source_thread, (surviving_source,) = await _thread_with_issues(
        db, user.id, "Delta Dangling Source", ["1"]
    )
    valid = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=valid_source.id,
        target_type="issue",
        target_id=valid_target.id,
        satisfaction_type="item_read",
    )
    specs = _allowlisted_dangling_specs(surviving_source.id, surviving_target.id)
    dangling_rules = [
        ContinuityRule(
            id=rule_id,
            user_id=user.id,
            source_type="issue",
            source_id=source_id,
            target_type="issue",
            target_id=target_id,
            satisfaction_type="item_read",
            note=f"continuity-plan:{plan.id}",
        )
        for rule_id, source_id, target_id in specs
    ]
    db.add_all([valid, *dangling_rules])
    await db.commit()
    original_fields = {
        rule_id: (source_id, target_id, f"continuity-plan:{plan.id}")
        for rule_id, source_id, target_id in specs
    }

    conn = _sync_connection()
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.canonical_backfill"):
            skipped = mig.validate_compilable_rules(conn)
        inserted, _skipped_existing = mig.backfill_item_read_edges(conn)
        _links, plan_skipped = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    assert len(skipped) == 6
    skipped_ids = {row.rule_id for row in skipped}
    assert skipped_ids == set(_ALLOWLISTED_RULE_IDS)
    for row in skipped:
        assert row.user_id == mig.REVIEWED_DANGLING_OWNER_USER_ID
        assert row.is_allowlisted()
        assert row.missing_sides()
        assert row.missing_issue_ids()
        report = row.report()
        assert f"user_id={row.user_id}" in report
        assert f"rule_id={row.rule_id}" in report
        assert "missing" in report
        for side in row.missing_sides():
            assert side in report
        for issue_id in row.missing_issue_ids():
            assert str(issue_id) in report
        assert report in caplog.text
    plan_by_id = dict(plan_skipped)
    for row in skipped:
        assert plan_by_id[row.rule_id] == row.report()
    assert inserted == 1

    edges = {
        (source_issue_id, target_issue_id)
        for source_issue_id, target_issue_id in await db.execute(
            sa.select(Dependency.source_issue_id, Dependency.target_issue_id)
        )
    }
    assert (valid_source.id, valid_target.id) in edges
    for _rule_id, source_id, target_id in specs:
        assert (source_id, target_id) not in edges

    remaining_rules = {
        rule_id: (source_id, target_id, note)
        for rule_id, source_id, target_id, note in await db.execute(
            sa.select(
                ContinuityRule.id,
                ContinuityRule.source_id,
                ContinuityRule.target_id,
                ContinuityRule.note,
            )
        )
    }
    for rule_id, fields in original_fields.items():
        assert remaining_rules[rule_id] == fields

    blocked = await _get_blocked_thread_ids_uncached(user.id, db)
    assert target_thread.id in blocked
    assert dangling_target_thread.id not in blocked
    assert dangling_source_thread.id not in blocked
    assert source_thread.id not in blocked

    conn = _sync_connection()
    try:
        removed = mig.revert_backfilled_edges(conn)
        conn.commit()
    finally:
        conn.close()
    assert removed == 1
    still_present = {
        rule_id
        for (rule_id,) in await db.execute(
            sa.select(ContinuityRule.id).where(
                ContinuityRule.id.in_(list(_ALLOWLISTED_RULE_IDS))
            )
        )
    }
    assert still_present == set(_ALLOWLISTED_RULE_IDS)


@pytest.mark.asyncio
async def test_validation_aborts_on_unknown_dangling_rule(
    _isolated_migration_data: AsyncSession,
) -> None:
    """A dangling rule outside the reviewed allowlist aborts, not warns."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-unknown-dangling-user")
    _, (surviving_target,) = await _thread_with_issues(
        db, user.id, "Unknown Dangling Target", ["1"]
    )
    unknown = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=999999,
        target_type="issue",
        target_id=surviving_target.id,
        satisfaction_type="item_read",
        note="user-owned prerequisite",
    )
    db.add(unknown)
    await db.commit()
    unknown_id = unknown.id
    original = (unknown.source_id, unknown.target_id, unknown.note, unknown.user_id)

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="not on the reviewed allowlist") as captured:
            mig.validate_compilable_rules(conn)
        message = str(captured.value)
        assert "silently weaken a user's prerequisites" in message
        assert f"user_id={user.id}" in message
        assert f"rule_id={unknown_id}" in message
        assert "missing source" in message
        assert "999999" in message
        assert "Offending rows:" in message
    finally:
        conn.close()

    remaining = (
        await db.execute(
            sa.select(
                ContinuityRule.source_id,
                ContinuityRule.target_id,
                ContinuityRule.note,
                ContinuityRule.user_id,
            ).where(ContinuityRule.id == unknown_id)
        )
    ).one()
    assert remaining == original
    edge_count = (
        await db.execute(sa.select(sa.func.count()).select_from(Dependency))
    ).scalar_one()
    assert edge_count == 0


@pytest.mark.asyncio
async def test_validation_aborts_when_allowlist_rule_id_has_wrong_owner(
    _isolated_migration_data: AsyncSession,
) -> None:
    """An allowlisted rule id owned by anyone other than user 23199 aborts."""
    db = _isolated_migration_data

    other = await _user(db, "cutover-stolen-allowlist-user")
    _, (surviving_target,) = await _thread_with_issues(
        db, other.id, "Stolen Allowlist Target", ["1"]
    )
    stolen_id = _ALLOWLISTED_RULE_IDS[0]
    stolen = ContinuityRule(
        id=stolen_id,
        user_id=other.id,
        source_type="issue",
        source_id=999999,
        target_type="issue",
        target_id=surviving_target.id,
        satisfaction_type="item_read",
    )
    db.add(stolen)
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="not on the reviewed allowlist") as captured:
            mig.validate_compilable_rules(conn)
        message = str(captured.value)
        assert f"user_id={other.id}" in message
        assert f"rule_id={stolen_id}" in message
        assert f"user_id={mig.REVIEWED_DANGLING_OWNER_USER_ID}" not in message.split(
            "Offending rows:"
        )[1]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_dangling_issue_and_unmatched_plan_skips_do_not_abort_each_other(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Allowlisted dangling skips and unmatched plan notes are independent.

    Prod had six item_read ``continuity-plan:N`` rules on missing issues, and
    859 rules whose ``continuity-plan:N`` note does not match a same-user
    plan. #3359 already skip-and-reports the latter. Neither check may abort
    on the other's allowlisted/plan-note cases, in either call order.
    """
    db = _isolated_migration_data

    owner = await _reviewed_dangling_owner(db)
    other = await _user(db, "cutover-skip-other")
    owner_plan = await _plan(db, owner.id, "Owner Plan")
    other_plan = await _plan(db, other.id, "Other Plan")
    _, (owned_source,) = await _thread_with_issues(db, owner.id, "Owned Source", ["1"])
    _, (owned_target,) = await _thread_with_issues(db, owner.id, "Owned Target", ["1"])
    _, (unmatched_source,) = await _thread_with_issues(
        db, owner.id, "Unmatched Source", ["1"]
    )
    _, (unmatched_target,) = await _thread_with_issues(
        db, owner.id, "Unmatched Target", ["1"]
    )
    _, (surviving_target,) = await _thread_with_issues(
        db, owner.id, "Surviving Target", ["1"]
    )

    dangling_id = _ALLOWLISTED_RULE_IDS[0]
    dangling_source_id = _PROD_MISSING_ISSUES[0]
    valid = ContinuityRule(
        user_id=owner.id,
        source_type="issue",
        source_id=owned_source.id,
        target_type="issue",
        target_id=owned_target.id,
        satisfaction_type="item_read",
        note=f"continuity-plan:{owner_plan.id}",
    )
    unmatched_plan = ContinuityRule(
        user_id=owner.id,
        source_type="issue",
        source_id=unmatched_source.id,
        target_type="issue",
        target_id=unmatched_target.id,
        satisfaction_type="item_read",
        note=f"continuity-plan:{other_plan.id}",
    )
    dangling = ContinuityRule(
        id=dangling_id,
        user_id=owner.id,
        source_type="issue",
        source_id=dangling_source_id,
        target_type="issue",
        target_id=surviving_target.id,
        satisfaction_type="item_read",
        note=f"continuity-plan:{owner_plan.id}",
    )
    db.add_all([valid, unmatched_plan, dangling])
    await db.commit()
    unmatched_id, valid_id = unmatched_plan.id, valid.id
    expected_report = mig.DanglingRuleReport(
        rule_id=dangling_id,
        user_id=owner.id,
        source_id=dangling_source_id,
        target_id=surviving_target.id,
        missing_source=True,
        missing_target=False,
    ).report()

    conn = _sync_connection()
    try:
        # Plan-note skip first: allowlisted dangling endpoints must not abort it.
        _links, plan_first_skipped = mig.link_plan_provenance(conn)
        plan_first_by_id = dict(plan_first_skipped)
        assert unmatched_id in plan_first_by_id
        assert "owned by user" in plan_first_by_id[unmatched_id]
        assert plan_first_by_id[dangling_id] == expected_report
        assert valid_id not in plan_first_by_id

        # Issue-existence skip second: unmatched plan notes must not abort it.
        dangling_skipped = mig.validate_compilable_rules(conn)
        skipped_ids = {row.rule_id for row in dangling_skipped}
        assert skipped_ids == {dangling_id}
        assert dangling_skipped[0].report() == expected_report
        assert unmatched_id not in skipped_ids
        assert valid_id not in skipped_ids

        inserted, _already = mig.backfill_item_read_edges(conn)
        links_created, plan_second_skipped = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    assert inserted == 2
    plan_second_by_id = dict(plan_second_skipped)
    assert unmatched_id in plan_second_by_id
    assert "owned by user" in plan_second_by_id[unmatched_id]
    assert plan_second_by_id[dangling_id] == expected_report
    assert links_created == 1

    edges = {
        (source_id, target_id)
        for source_id, target_id in await db.execute(
            sa.select(Dependency.source_issue_id, Dependency.target_issue_id)
        )
    }
    assert (owned_source.id, owned_target.id) in edges
    assert (unmatched_source.id, unmatched_target.id) in edges
    assert (dangling_source_id, surviving_target.id) not in edges

    remaining = (
        await db.execute(
            sa.select(
                ContinuityRule.source_id,
                ContinuityRule.target_id,
                ContinuityRule.note,
            ).where(ContinuityRule.id == dangling_id)
        )
    ).one()
    assert remaining == (
        dangling_source_id,
        surviving_target.id,
        f"continuity-plan:{owner_plan.id}",
    )


@pytest.mark.asyncio
async def test_backfill_is_idempotent(_isolated_migration_data: AsyncSession) -> None:
    """Running the backfill twice creates no duplicate edges or links."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-idempotent-user")
    plan = await _plan(db, user.id, "Idempotent Plan")
    _, (a1,) = await _thread_with_issues(db, user.id, "Epsilon", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Zeta", ["1"])
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
            note=f"continuity-plan:{plan.id}",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        first_edges, _ = mig.backfill_item_read_edges(conn)
        first_links, _ = mig.link_plan_provenance(conn)
        second_edges, _ = mig.backfill_item_read_edges(conn)
        second_links, _ = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    assert first_edges == 1
    assert first_links == 1
    assert second_edges == 0
    assert second_links == 0


@pytest.mark.asyncio
async def test_validation_aborts_on_cross_user_issue_reference(
    _isolated_migration_data: AsyncSession,
) -> None:
    """A rule pointing at another user's issues aborts (clone-provenance hazard)."""
    db = _isolated_migration_data

    owner = await _user(db, "cutover-owner-user")
    other = await _user(db, "cutover-other-user")
    _, (a1,) = await _thread_with_issues(db, owner.id, "Theta", ["1"])
    _, (b1,) = await _thread_with_issues(db, other.id, "Iota", ["1"])
    db.add(
        ContinuityRule(
            user_id=owner.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="different user than the rule"):
            mig.validate_compilable_rules(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_validation_aborts_on_non_issue_endpoints(
    _isolated_migration_data: AsyncSession,
) -> None:
    """An item_read rule with thread-level endpoints aborts the migration."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-endpoint-user")
    thread, (a1,) = await _thread_with_issues(db, user.id, "Kappa", ["1"])
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="crossover",
            source_id=thread.id,
            target_type="issue",
            target_id=a1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="non-issue endpoints"):
            mig.validate_compilable_rules(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backfill_scales_to_hundreds_of_rules(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Set-based backfill handles a few hundred rules without per-row Python."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-scale-user")
    # 10 threads x 10 issues; chain issue i -> issue i+1 across the whole set.
    all_issues: list[Issue] = []
    for t in range(10):
        _, issues = await _thread_with_issues(
            db, user.id, f"ScaleThread{t}", [str(n) for n in range(10)]
        )
        all_issues.extend(issues)
    db.add_all(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=all_issues[i].id,
            target_type="issue",
            target_id=all_issues[i + 1].id,
            satisfaction_type="item_read",
        )
        for i in range(len(all_issues) - 1)
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        inserted, skipped = mig.backfill_item_read_edges(conn)
        conn.commit()
    finally:
        conn.close()

    assert inserted == len(all_issues) - 1
    assert skipped == 0


@pytest.mark.asyncio
async def test_backfill_aborts_on_cbl_collision(
    _isolated_migration_data: AsyncSession,
) -> None:
    """A rule colliding with an inert cbl-order row aborts, not silently skips."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-collision-user")
    _, (a1,) = await _thread_with_issues(db, user.id, "Lambda", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Mu", ["1"])
    # Historical CBL row occupies the pair the rule must compile.
    db.add(
        Dependency(
            source_issue_id=a1.id,
            target_issue_id=b1.id,
            note="cbl-order:source:abc123:1->2",
        )
    )
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="collide with historical cbl-order"):
            mig.backfill_item_read_edges(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_validation_aborts_when_rule_edges_form_a_cycle(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Rule pairs plus existing canonical edges that cycle abort with the rule ids."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-cycle-user")
    _, (a1,) = await _thread_with_issues(db, user.id, "Cycle A", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Cycle B", ["1"])
    db.add(
        Dependency(
            source_issue_id=a1.id,
            target_issue_id=b1.id,
            note="genuine prerequisite",
        )
    )
    reverse = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=b1.id,
        target_type="issue",
        target_id=a1.id,
        satisfaction_type="item_read",
    )
    db.add(reverse)
    await db.commit()
    rule_id = reverse.id

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="dependency cycle") as captured:
            mig.validate_compilable_rules(conn)
        assert str(rule_id) in str(captured.value)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_downgrade_keeps_live_write_path_edges(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Alembic downgrade deletes backfill notes only, not later canonical:rule: rows."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-downgrade-user")
    _, (a1,) = await _thread_with_issues(db, user.id, "Downgrade A", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Downgrade B", ["1"])
    _, (c1,) = await _thread_with_issues(db, user.id, "Downgrade C", ["1"])
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        inserted, _skipped = mig.backfill_item_read_edges(conn)
        conn.commit()
        assert inserted == 1
        conn.execute(
            sa.text(
                "INSERT INTO dependencies (source_issue_id, target_issue_id, note, created_at) "
                "VALUES (:src, :tgt, :note, now())"
            ),
            {
                "src": b1.id,
                "tgt": c1.id,
                "note": f"{EDGE_NOTE_PREFIX}99999",
            },
        )
        conn.commit()
        removed = mig.revert_backfilled_edges(conn)
        conn.commit()
        assert removed == 1
    finally:
        conn.close()

    notes = {
        (source_id, target_id): note
        for source_id, target_id, note in await db.execute(
            sa.select(Dependency.source_issue_id, Dependency.target_issue_id, Dependency.note)
        )
    }
    assert (a1.id, b1.id) not in notes
    assert notes[(b1.id, c1.id)] == f"{EDGE_NOTE_PREFIX}99999"


@pytest.mark.asyncio
async def test_resave_then_downgrade_keeps_refreshed_edge(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Re-saving after cutover retargets the note so downgrade will not delete it."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-resave-user")
    _, (a1,) = await _thread_with_issues(db, user.id, "Resave A", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Resave B", ["1"])
    rule = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=a1.id,
        target_type="issue",
        target_id=b1.id,
        satisfaction_type="item_read",
    )
    db.add(rule)
    await db.commit()
    a_id, b_id, rule_id = a1.id, b1.id, rule.id

    conn = _sync_connection()
    try:
        mig.backfill_item_read_edges(conn)
        conn.commit()
        conn.execute(
            sa.text(
                "UPDATE dependencies SET note = :note "
                "WHERE source_issue_id = :src AND target_issue_id = :tgt"
            ),
            {"note": f"{EDGE_NOTE_PREFIX}{rule_id}", "src": a_id, "tgt": b_id},
        )
        conn.commit()
        removed = mig.revert_backfilled_edges(conn)
        conn.commit()
        assert removed == 0
    finally:
        conn.close()

    remaining = (
        await db.execute(
            sa.select(Dependency.note).where(
                Dependency.source_issue_id == a_id,
                Dependency.target_issue_id == b_id,
            )
        )
    ).scalar_one()
    assert remaining == f"{EDGE_NOTE_PREFIX}{rule_id}"
