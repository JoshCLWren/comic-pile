"""Behavioral safety fixtures for the read-only Option E provenance census."""

from dataclasses import replace

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from app.models.continuity_rule import ContinuityRule
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency
from scripts.report_dependency_provenance import (
    KNOWN_FRONTIER_THREAD_IDS,
    Snapshot,
    census,
    load_snapshot,
    report,
    main,
)


def fixture_snapshot() -> Snapshot:
    """Include a completed shell, skipped frontier, unknown notes and colliding rules."""
    threads = [
        Thread(id=18849, user_id=1, title="Parent", status="active", next_unread_issue_id=12,
               total_issues=3, issues_remaining=3, is_blocked=True),
        Thread(id=18852, user_id=1, title="Shell", status="completed", next_unread_issue_id=11,
               total_issues=1, issues_remaining=1, is_blocked=True),
        Thread(id=2, user_id=1, title="Other", status="active", next_unread_issue_id=20,
               is_blocked=False),
    ]
    issues = [
        Issue(id=12, thread_id=18849, position=2, status="unread"),
        Issue(id=11, thread_id=18849, position=1, status="unread"),
        Issue(id=10, thread_id=18849, position=0, status="read"),
        Issue(id=20, thread_id=2, position=1, status="unread"),
    ]
    edges = [
        Dependency(id=1, source_issue_id=20, target_issue_id=11, note="canonical:rule:5"),
        Dependency(id=2, source_issue_id=11, target_issue_id=12, note=None),
        Dependency(id=3, source_issue_id=10, target_issue_id=20, note="reader?"),
        Dependency(id=4, source_issue_id=20, target_issue_id=12, note="cbl-order:old"),
        Dependency(id=5, source_issue_id=99, target_issue_id=20, note="canonical:rule:999"),
    ]
    rules = [ContinuityRule(
        id=i, user_id=1, source_type="issue", source_id=20, target_type="issue", target_id=11,
        satisfaction_type="checkpoint" if i == 5 else "item_read",
        checkpoint_issue_id=20 if i == 5 else None,
        legacy_dependency_id=None, note="plan:old" if i == 5 else "overwritten history",
    ) for i in (5, 6)]
    entries = [CustomCBLEntry(id=i, list_id=i, issue_id=issue_id, position=1)
               for i, issue_id in ((1, 20), (2, 11))]
    plans = [ReadingPlanDependency(plan_id=7, dependency_id=1, explanation="legacy placement")]
    return Snapshot(threads, issues, edges, rules, entries, plans)


def test_collisions_and_unknown_authorship_remain_unknown() -> None:
    """A compiler note never discards colliding evidence or proves reader authorship."""
    result = census(fixture_snapshot(), 1)
    edges = result["edges"]
    assert isinstance(edges, list)
    assert [e["dependency_id"] for e in edges] == [1, 2, 3, 5]
    assert [e["evidence_class"] for e in edges] == ["D"] * 4
    assert [r["rule_id"] for r in edges[0]["rule_evidence"]] == [5, 6]
    assert edges[0]["plan_evidence"] == [{"plan_id": 7, "explanation": "legacy placement"}]
    assert edges[0]["cross_list"] is True
    assert edges[0]["active_derived_frontier_blocker"] is True
    assert edges[0]["active_stored_frontier_blocker"] is False
    assert edges[1]["same_thread"] is True
    assert edges[2]["active_derived_frontier_blocker"] is False
    assert edges[3]["unresolved_endpoint"] is True
    assert edges[3]["missing_note_rule"] is True
    assert result["summary"] == {
        "enforced_edges": 4, "inert_cbl_order_edges": 1,
        "same_thread_edges": 1, "cross_thread_edges": 2, "cross_list_edges": 1,
        "evidence_classes": {"D": 4}, "active_derived_frontier_blockers": 1,
        "active_stored_frontier_blockers": 1, "frontier_mismatches": 2,
    }


def test_single_matching_checkpoint_is_evidence_not_approval() -> None:
    """Only unambiguous checkpoint evidence yields observational class B."""
    snapshot = fixture_snapshot()
    result = census(replace(snapshot, rules=snapshot.rules[:1]), 1)
    edges = result["edges"]
    assert isinstance(edges, list)
    assert edges[0]["evidence_class"] == "D"
    assert edges[0]["rule_evidence"][0]["matches_compiled_pair"] is True
    assert result["read_only"] is True


def test_all_known_threads_are_accounted_for_regardless_of_status() -> None:
    """Completed shells and missing IDs remain explicit, without changing pointers."""
    snapshot = fixture_snapshot()
    result = census(snapshot, 1)
    known = result["known_3588_threads"]
    assert isinstance(known, list)
    assert len(known) == 24
    assert {r["thread_id"] for r in known} == set(KNOWN_FRONTIER_THREAD_IDS)
    parent, shell, missing = known[:3]
    assert parent["derived_next_issue_id"] == 11
    assert shell["status"] == "completed"
    assert shell["derived_next_issue_id"] is None
    assert shell["stored_pointer_in_thread"] is False
    assert shell["stored_pointer_owned_thread_id"] == 18849
    assert missing == {"thread_id": 18854, "missing_or_deleted": True}
    assert snapshot.threads[0].next_unread_issue_id == 12
    assert snapshot.threads[1].status == "completed"


def test_census_is_deterministic_and_does_not_infer_from_titles() -> None:
    """Input order and annual labels cannot change evidence or derived frontier."""
    snapshot = fixture_snapshot()
    first = census(snapshot, 1)
    assert census(replace(snapshot, threads=list(reversed(snapshot.threads)),
                          issues=list(reversed(snapshot.issues)),
                          dependencies=list(reversed(snapshot.dependencies)),
                          rules=list(reversed(snapshot.rules))), 1) == first
    snapshot.issues[1].issue_number = "Annual #2"
    assert census(snapshot, 1) == first


@pytest.mark.parametrize("url", ["sqlite:///file", "postgresql://localhost/db", ""])
async def test_explicit_asyncpg_url_required(url: str) -> None:
    """The report never falls back to an implicit configured production URL."""
    with pytest.raises(ValueError, match="explicit postgresql"):
        await report(url, 1)


async def test_database_snapshot_is_scoped_and_does_not_flush(async_db: AsyncSession) -> None:
    """Owned all-status rows load; other readers' data and dirty writes stay private."""
    user = User(username="census-owner", password_hash="unused")
    foreign = User(username="census-foreign", password_hash="unused")
    async_db.add_all([user, foreign])
    await async_db.flush()
    thread = Thread(user_id=user.id, title="Completed", status="completed", format="Comic",
                    queue_position=1, issues_remaining=1)
    other = Thread(user_id=foreign.id, title="Private", status="active", format="Comic",
                   queue_position=1, issues_remaining=1)
    async_db.add_all([thread, other])
    await async_db.flush()
    left = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    right = Issue(thread_id=other.id, issue_number="1", position=1, status="unread")
    async_db.add_all([left, right])
    await async_db.flush()
    edge = Dependency(source_issue_id=left.id, target_issue_id=right.id, note="unknown")
    custom = CustomCBLList(user_id=user.id, name="Owner")
    private = CustomCBLList(user_id=foreign.id, name="Private")
    async_db.add_all([edge, custom, private])
    await async_db.flush()
    async_db.add_all([
        CustomCBLEntry(list_id=custom.id, issue_id=left.id, position=1),
        CustomCBLEntry(list_id=private.id, issue_id=left.id, position=1),
    ])
    await async_db.flush()
    with async_db.no_autoflush:
        snapshot = await load_snapshot(async_db, user.id)
        assert [t.id for t in snapshot.threads] == [thread.id]
        assert [i.id for i in snapshot.issues] == [left.id]
        assert [e.list_id for e in snapshot.entries] == [custom.id]
        assert [e.id for e in snapshot.dependencies] == [edge.id]
        result = census(snapshot, user.id)
        assert "Private" not in str(result)
        assert not async_db.new
        assert not async_db.dirty
    assert (await async_db.scalar(select(Issue.status).where(Issue.id == left.id))) == "unread"


async def test_report_uses_database_enforced_read_only_snapshot(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify PostgreSQL itself forbids writes in the report transaction."""
    import scripts.report_dependency_provenance as module

    original = module.load_snapshot
    observed = []

    async def checked_snapshot(db: AsyncSession, user_id: int) -> Snapshot:
        observed.append(await db.scalar(text("SHOW transaction_read_only")))
        observed.append(await db.scalar(text("SHOW transaction_isolation")))
        assert db.autoflush is False
        return await original(db, user_id)

    monkeypatch.setattr(module, "load_snapshot", checked_snapshot)
    result = await report(db_engine.url.render_as_string(hide_password=False), 987654321)
    assert observed == ["on", "repeatable read"]
    assert result["edges"] == []
    assert result["frontiers"] == []


def test_cli_emits_complete_json(monkeypatch: pytest.MonkeyPatch,
                                 capsys: pytest.CaptureFixture[str]) -> None:
    """CLI output preserves unknown evidence and the complete missing-ID cohort."""
    import json
    import sys
    from unittest.mock import AsyncMock

    import scripts.report_dependency_provenance as module

    expected = census(fixture_snapshot(), 1)
    monkeypatch.setattr(module, "report", AsyncMock(return_value=expected))
    monkeypatch.setattr(sys, "argv", ["census", "--database-url", "explicit", "--user-id", "1"])
    main()
    assert json.loads(capsys.readouterr().out) == expected


def test_dangling_and_malformed_note_rules_remain_unknown() -> None:
    """A mismatching or malformed historical rule cannot hide an enforced edge."""
    snapshot = fixture_snapshot()
    rule = snapshot.rules[0]
    rule.satisfaction_type = "converged"
    rule.convergence_targets = [{"type": "issue", "id": "not-an-id"}]
    result = census(replace(snapshot, rules=[rule]), 1)
    edges = result["edges"]
    assert isinstance(edges, list)
    assert len(edges) == 4
    assert edges[0]["evidence_class"] == "D"
    assert edges[0]["rule_evidence"][0]["matches_compiled_pair"] is False
    assert edges[0]["rule_evidence"][0]["convergence_targets"] == rule.convergence_targets


def test_malformed_rule_note_does_not_infer_checkpoint_provenance() -> None:
    """Malformed compiler notes retain matching rules without granting authorship."""
    snapshot = fixture_snapshot()
    snapshot.dependencies[0].note = "canonical:rule:invalid"
    result = census(replace(snapshot, rules=snapshot.rules[:1]), 1)
    edges = result["edges"]
    assert isinstance(edges, list)
    edge = edges[0]
    assert edge["evidence_class"] == "D"
    assert edge["missing_note_rule"] is True
    assert edge["rule_evidence"][0]["matches_compiled_pair"] is True


def test_foreign_source_to_owned_frontier_is_not_confirmed_blocker() -> None:
    """Preserve foreign-source evidence without counting it as a live blocker."""
    snapshot = fixture_snapshot()
    edge = Dependency(id=9, source_issue_id=999, target_issue_id=11, note="foreign")
    result = census(replace(snapshot, dependencies=[edge]), 1)
    edges = result["edges"]
    assert isinstance(edges, list)
    reported = edges[0]
    assert reported["unresolved_endpoint"] is True
    assert reported["active_derived_frontier_blocker"] is False
    assert reported["active_stored_frontier_blocker"] is False
    summary = result["summary"]
    assert isinstance(summary, dict)
    assert summary["active_derived_frontier_blockers"] == 0
