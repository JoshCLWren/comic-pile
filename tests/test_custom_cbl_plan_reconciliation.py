"""Regression evidence for the read-only Option E list/plan census."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.continuity_plan import ContinuityPlan
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanIssue,
    ReadingPlanSource,
    ReadingPlanSourcePlacement,
)
from scripts.report_custom_cbl_plan_reconciliation import Snapshot, load_snapshot, reconcile
from scripts import report_custom_cbl_plan_reconciliation as census


@pytest.mark.parametrize(
    ("name", "shared_ids", "list_only_ids", "plan_only_ids"),
    [
        ("Absolute", [100000 + i * 7 for i in range(76)], [200000 + i * 11 for i in range(29)], []),
        ("Julix Mignolaverse", [300000 + i * 7 for i in range(464)], [700001, 700003], []),
        ("JSA", [117189] + [400000 + i * 7 for i in range(56)], [], [26360]),
    ],
)
def test_documented_membership_gaps(
    name: str, shared_ids: list[int], list_only_ids: list[int], plan_only_ids: list[int]
) -> None:
    """Named acceptance scenarios with synthetic surrounding membership.

    Julix IDs stand for Box Full of Evil #1 and Amazing Screw-On Head #1;
    Starman #55 uses the stable ADR identity 26360.
    """
    custom_list = CustomCBLList(id=1, user_id=9, name=name)
    plan = ContinuityPlan(id=2, user_id=9, name=name, nodes_json=[])
    fixture_titles = {700001: "Box Full of Evil #1", 700003: "Amazing Screw-On Head #1"}
    list_ids = shared_ids + list_only_ids
    plan_ids = plan_only_ids + shared_ids
    entries = [
        CustomCBLEntry(
            id=i,
            list_id=1,
            issue_id=issue_id,
            position=i,
            is_checkpoint=False,
            checkpoint_target_issue_ids=[],
        )
        for i, issue_id in enumerate(list_ids, 1)
    ]
    issues = [
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id=str(i),
            issue_id=issue_id,
            lane_id="main",
            display_position=i,
            is_checkpoint=False,
        )
        for i, issue_id in enumerate(plan_ids, 1)
    ]
    plan.nodes_json = [{"node_type": "issue", "ref_id": issue_id} for issue_id in plan_ids]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path=name)
    result = reconcile(Snapshot([custom_list], entries, [plan], issues, [source]), 9)
    rows = result["lists"]
    assert isinstance(rows, list)
    row = rows[0]
    assert isinstance(row, dict)
    list_only = row["list_only"]
    plan_only = row["plan_only"]
    assert isinstance(list_only, list) and all(isinstance(item, dict) for item in list_only)
    assert isinstance(plan_only, list) and all(isinstance(item, dict) for item in plan_only)
    assert all(isinstance(item, dict) for item in list_only)
    assert all(isinstance(item, dict) for item in plan_only)
    assert {item["issue_id"] for item in list_only} == set(list_only_ids)
    assert {item["issue_id"] for item in plan_only} == set(plan_only_ids)
    assert len(list_only) == len(list_only_ids)
    assert len(plan_only) == len(plan_only_ids)
    assert row["resolution"] == "unresolved"
    assert row["list_count"] == len(list_ids)
    assert row["plan_count"] == len(plan_ids)
    if name == "Julix Mignolaverse":
        assert [fixture_titles[item["issue_id"]] for item in list_only] == [
            "Box Full of Evil #1",
            "Amazing Screw-On Head #1",
        ]
    if name == "JSA":
        assert 26360 not in list_ids and 26360 in plan_ids


def test_unlinked_projects_are_not_paired_by_name() -> None:
    """Identical titles never substitute for explicit source provenance."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Same")
    plan = ContinuityPlan(id=2, user_id=9, name="Same", nodes_json=[])
    result = reconcile(Snapshot([custom_list], [], [plan], [], []), 9)
    lists = result["lists"]
    plans = result["unpaired_plans"]
    assert isinstance(lists, list) and isinstance(lists[0], dict)
    assert isinstance(plans, list) and isinstance(plans[0], dict)
    assert lists[0]["status"] == "unpaired_list"
    assert plans[0]["plan_id"] == 2


def test_unpaired_checkpoint_targets_are_preserved() -> None:
    """An unpaired list exposes targets behind its checkpoint anomaly."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Unpaired")
    entry = CustomCBLEntry(
        id=2,
        list_id=1,
        issue_id=10,
        position=3,
        is_checkpoint=True,
        checkpoint_target_issue_ids=[20, 30],
    )
    rows = reconcile(Snapshot([custom_list], [entry], [], [], []), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["entries"] == [
        {
            "entry_id": 2,
            "gate": None,
            "skipped": None,
            "issue_id": 10,
            "position": 3,
            "checkpoint": True,
            "checkpoint_target_issue_ids": [20, 30],
        }
    ]
    assert "unclassified_list_checkpoint_evidence" in rows[0]["anomalies"]


def test_order_skip_and_source_provenance_remain_visible() -> None:
    """A shared membership can still have unresolved order and skip evidence."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Ordered")
    entries = [
        CustomCBLEntry(id=1, list_id=1, issue_id=10, position=1),
        CustomCBLEntry(id=2, list_id=1, issue_id=20, position=2),
    ]
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Ordered",
        nodes_json=[
            {"node_type": "issue", "ref_id": 10},
            {"node_type": "issue", "ref_id": 20},
        ],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id="a",
            issue_id=20,
            lane_id="main",
            display_position=1,
            reader_optional=True,
        ),
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id="b",
            issue_id=10,
            lane_id="main",
            display_position=2,
            source_metadata_json={"skip": True},
        ),
    ]
    source = ReadingPlanSource(
        id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path="curated.cbl", revision_sha="abc"
    )
    placement = ReadingPlanSourcePlacement(
        id=4, plan_id=2, occurrence_id="a", plan_source_id=3, source_position=42
    )
    result = reconcile(Snapshot([custom_list], entries, [plan], issues, [source], [placement]), 9)
    rows = result["lists"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert row["order_conflict"] is True
    assert row["resolution"] == "unresolved"
    assert row["plan_optional_or_skipped_evidence"] == [
        {
            "issue_id": 20,
            "occurrence_id": "a",
            "lane_id": "main",
            "reader_optional": True,
            "reader_role": None,
            "source_metadata": None,
        },
        {
            "issue_id": 10,
            "occurrence_id": "b",
            "lane_id": "main",
            "reader_optional": None,
            "reader_role": None,
            "source_metadata": {"skip": True},
        },
    ]
    assert row["source_placements"] == [
        {"occurrence_id": "a", "source_id": 3, "source_position": 42}
    ]


def test_multilane_order_and_malformed_nodes_are_reported() -> None:
    """Each lane has its own order evidence and JSON defects remain visible."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Lanes")
    entries = [CustomCBLEntry(id=i, list_id=1, issue_id=i, position=i) for i in (1, 2, 3)]
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Lanes",
        nodes_json=[
            {"node_type": "issue", "ref_id": 1},
            {"node_type": "issue", "ref_id": 2},
            {"node_type": "issue", "ref_id": 3},
            {"node_type": "issue", "ref_id": 3},
            {"node_type": "issue", "ref_id": "bad"},
        ],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id=str(i),
            issue_id=issue_id,
            lane_id=lane,
            display_position=position,
        )
        for i, (issue_id, lane, position) in enumerate([(2, "a", 1), (1, "a", 2), (3, "b", 1)], 1)
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path="curated.cbl")
    rows = reconcile(Snapshot([custom_list], entries, [plan], issues, [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    row = rows[0]
    assert row["order_conflict"] is None
    assert row["lane_orders"][0] == {
        "lane_id": "a",
        "list_order": [1, 2],
        "plan_order": [2, 1],
        "full_plan_order": [2, 1],
        "order_conflict": True,
    }
    assert row["duplicate_plan_issue_node_ids"] == [3]
    assert row["malformed_plan_nodes"] == [
        {"index": 4, "node": {"node_type": "issue", "ref_id": "bad"}}
    ]
    assert "extra_lanes_order_unresolved" in row["anomalies"]


def test_foreign_source_link_is_redacted_but_reported() -> None:
    """A stale cross-user source cannot reveal the other user's list ID."""
    plan = ContinuityPlan(id=2, user_id=9, name="Orphan", nodes_json=[])
    source = ReadingPlanSource(
        id=3, plan_id=2, custom_cbl_list_id=987654, raw_source_path="orphan.cbl"
    )
    result = reconcile(Snapshot([], [], [plan], [], [source]), 9)
    rows = result["unpaired_plans"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["sources"][0]["custom_cbl_list_id"] is None
    assert rows[0]["sources"][0]["foreign_or_missing_list_link"] is True
    assert rows[0]["anomalies"] == ["foreign_or_missing_list_link"]
    assert "987654" not in str(result)


def test_plan_only_lane_member_keeps_its_order() -> None:
    """Full lane order retains members absent from the Custom CBL."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Lanes")
    entry = CustomCBLEntry(id=1, list_id=1, issue_id=10, position=1)
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Lanes",
        nodes_json=[
            {"node_type": "issue", "ref_id": 20},
            {"node_type": "issue", "ref_id": 10},
        ],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2, occurrence_id=str(i), issue_id=issue_id, lane_id="extra", display_position=i
        )
        for i, issue_id in enumerate((20, 10), 1)
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    rows = reconcile(Snapshot([custom_list], [entry], [plan], issues, [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["lane_orders"][0]["full_plan_order"] == [20, 10]
    assert rows[0]["lane_orders"][0]["plan_order"] == [10]


def test_jsa_boundary_reports_exact_records() -> None:
    """A plan-only member is reported including Starman #55."""
    custom_list = CustomCBLList(id=1, user_id=9, name="JSA")
    entry = CustomCBLEntry(id=1, list_id=1, issue_id=117189, position=1)
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="JSA",
        nodes_json=[
            {"node_type": "issue", "ref_id": 26360},
            {"node_type": "issue", "ref_id": 117189},
        ],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id="starman-55",
            issue_id=26360,
            lane_id="main",
            display_position=1,
        ),
        ReadingPlanIssue(
            plan_id=2,
            occurrence_id="all-star-1",
            issue_id=117189,
            lane_id="main",
            display_position=2,
        ),
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path="JSA.cbl")
    rows = reconcile(Snapshot([custom_list], [entry], [plan], issues, [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    row = rows[0]
    assert row["plan_only"] == [
        {
            "issue_id": 26360,
            "occurrence_id": "starman-55",
            "is_checkpoint": None,
            "lane_id": "main",
            "position": 1,
            "reader_optional": None,
            "reader_role": None,
            "source_metadata": None,
        }
    ]
    assert row["position_conflicts"] == [
        {"issue_id": 117189, "list_position": 1, "plan_position": 2, "plan_lane_id": "main"}
    ]
    assert "shared_issue_position_conflict" in row["anomalies"]
    assert [item["issue_id"] for item in row["plan_only"]] == [26360]


def test_plan_linked_to_multiple_lists_is_unresolved() -> None:
    """Shared plan membership is never attributed to either linked list."""
    lists = [CustomCBLList(id=i, user_id=9, name=f"List {i}") for i in (1, 2)]
    plan = ContinuityPlan(
        id=3,
        user_id=9,
        name="Shared",
        nodes_json=[
            {"node_type": "issue", "ref_id": 30},
        ],
    )
    entries = [CustomCBLEntry(id=i, list_id=i, issue_id=i * 10, position=1) for i in (1, 2)]
    issue = ReadingPlanIssue(
        plan_id=3, occurrence_id="shared", issue_id=30, lane_id="main", display_position=1
    )
    sources = [
        ReadingPlanSource(
            id=i + 10, plan_id=3, custom_cbl_list_id=i, raw_source_path=f"list-{i}.cbl"
        )
        for i in (1, 2)
    ]
    reports = reconcile(Snapshot(lists, entries, [plan], [issue], sources), 9)["lists"]
    assert isinstance(reports, list)
    assert len(reports) == 2
    assert all(
        isinstance(row, dict)
        and row["status"] == "ambiguous_link"
        and row["resolution"] == "unresolved"
        and row["linked_list_ids"] == [1, 2]
        and row["plan_issues"][0]["issue_id"] == 30
        and "list_only" not in row
        and "plan_only" not in row
        and "lane_orders" not in row
        and "position_conflicts" not in row
        for row in reports
    )


def test_ambiguous_link_preserves_malformed_and_mismatched_plan_nodes() -> None:
    """Ambiguous pairing does not hide independent plan JSON defects."""
    lists = [CustomCBLList(id=i, user_id=9, name=f"List {i}") for i in (1, 2)]
    plan = ContinuityPlan(
        id=3,
        user_id=9,
        name="Shared",
        nodes_json=[
            {"node_type": "issue", "ref_id": "bad"},
            {"node_type": "issue", "ref_id": 99},
        ],
    )
    issue = ReadingPlanIssue(
        plan_id=3, occurrence_id="a", issue_id=30, lane_id="main", display_position=1
    )
    sources = [ReadingPlanSource(id=10 + i, plan_id=3, custom_cbl_list_id=i) for i in (1, 2)]
    rows = reconcile(Snapshot(lists, [], [plan], [issue], sources), 9)["lists"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        assert row["plan_nodes"] == plan.nodes_json
        assert row["malformed_plan_nodes"] == [
            {"index": 0, "node": {"node_type": "issue", "ref_id": "bad"}}
        ]
        assert "malformed_plan_nodes" in row["anomalies"]
        assert "plan_json_membership_mismatch" in row["anomalies"]
        assert row["resolution"] == "unresolved"


def test_duplicate_list_entries_preserve_every_occurrence() -> None:
    """Duplicate issue rows remain visible with their distinct IDs and positions."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Duplicate list")
    entries = [CustomCBLEntry(id=i, list_id=1, issue_id=10, position=i) for i in (1, 2)]
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Plan",
        nodes_json=[
            {"node_type": "issue", "ref_id": 10},
        ],
    )
    issue = ReadingPlanIssue(
        plan_id=2, occurrence_id="a", issue_id=10, lane_id="main", display_position=1
    )
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    rows = reconcile(Snapshot([custom_list], entries, [plan], [issue], [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    row = rows[0]
    assert row["duplicate_list_membership_issue_ids"] == [10]
    assert row["duplicate_list_entries"] == row["list_entries"]
    assert [item["entry_id"] for item in row["duplicate_list_entries"]] == [1, 2]
    assert "duplicate_list_membership_issues" in row["anomalies"]
    assert row["resolution"] == "unresolved"


@pytest.mark.parametrize("nodes", [None, {"unexpected": "object"}, "bad"])
def test_malformed_plan_node_container_is_evidence(nodes: object) -> None:
    """Null and non-list plan JSON are reported without an enumeration error."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Malformed")
    plan = ContinuityPlan(id=2, user_id=9, name="Malformed", nodes_json=nodes)
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    rows = reconcile(Snapshot([custom_list], [], [plan], [], [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["plan_nodes"] == nodes
    assert rows[0]["malformed_plan_nodes"] == [{"container": nodes}]
    assert "malformed_plan_nodes" in rows[0]["anomalies"]
    assert rows[0]["resolution"] == "unresolved"


def test_position_conflict_without_order_conflict_is_unresolved() -> None:
    """A shifted shared position is still a discrepancy when order agrees."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Shifted")
    entry = CustomCBLEntry(id=1, list_id=1, issue_id=10, position=1)
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Shifted",
        nodes_json=[
            {"node_type": "issue", "ref_id": 10},
        ],
    )
    issue = ReadingPlanIssue(
        plan_id=2, occurrence_id="a", issue_id=10, lane_id="main", display_position=4
    )
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path="shifted.cbl")
    reports = reconcile(Snapshot([custom_list], [entry], [plan], [issue], [source]), 9)["lists"]
    assert isinstance(reports, list) and isinstance(reports[0], dict)
    assert reports[0]["order_conflict"] is False
    assert reports[0]["position_conflicts"] == [
        {"issue_id": 10, "list_position": 1, "plan_position": 4, "plan_lane_id": "main"},
    ]
    assert "shared_issue_position_conflict" in reports[0]["anomalies"]
    assert reports[0]["resolution"] == "unresolved"


def test_duplicate_plan_membership_is_unresolved() -> None:
    """A duplicate shared issue cannot disappear through set comparison."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Duplicate")
    entry = CustomCBLEntry(id=1, list_id=1, issue_id=10, position=1)
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Duplicate",
        nodes_json=[
            {"node_type": "issue", "ref_id": 10},
            {"node_type": "issue", "ref_id": 10},
        ],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2, occurrence_id=str(i), issue_id=10, lane_id="main", display_position=i
        )
        for i in (1, 2)
    ]
    source = ReadingPlanSource(
        id=3, plan_id=2, custom_cbl_list_id=1, raw_source_path="duplicate.cbl"
    )
    reports = reconcile(Snapshot([custom_list], [entry], [plan], issues, [source]), 9)["lists"]
    assert isinstance(reports, list) and isinstance(reports[0], dict)
    row = reports[0]
    assert row["list_only"] == [] and row["plan_only"] == []
    assert row["duplicate_plan_membership_issue_ids"] == [10]
    assert "duplicate_plan_membership_issues" in row["anomalies"]
    assert row["resolution"] == "unresolved"


def test_summary_prints_discrepancy_and_provenance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Human-readable mode exposes item discrepancies and their evidence."""

    async def fake_report(database_url: str, user_id: int) -> dict[str, object]:
        assert database_url == "postgresql+asyncpg://unused" and user_id == 9
        return {
            "summary": {"list_count": 1},
            "unpaired_plans": [],
            "lists": [
                {
                    "list_id": 1,
                    "list_name": "Example",
                    "status": "paired",
                    "list_count": 2,
                    "anomalies": ["membership_difference"],
                    "list_only": [{"issue_id": 10}],
                    "plan_only": [{"issue_id": 20}],
                    "position_conflicts": [
                        {"issue_id": 30, "list_position": 1, "plan_position": 2}
                    ],
                    "plan_optional_or_skipped_evidence": [
                        {"issue_id": 20, "reader_optional": True}
                    ],
                    "sources": [{"raw_source_path": "curated.cbl"}],
                }
            ],
        }

    monkeypatch.setattr(census, "report", fake_report)
    monkeypatch.setattr(
        sys,
        "argv",
        ["census", "--database-url", "postgresql+asyncpg://unused", "--user-id", "9", "--summary"],
    )
    census.main()
    output = capsys.readouterr().out
    for evidence in (
        "list_only",
        "plan_only",
        "position_conflicts",
        "plan_optional_or_skipped_evidence",
        "curated.cbl",
    ):
        assert evidence in output


def test_snapshot_queries_are_user_scoped_selects() -> None:
    """An empty user's census issues only scoped read queries."""
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    snapshot = asyncio.run(load_snapshot(db, 9))
    assert snapshot.lists == [] and snapshot.plans == []
    queries = [str(call.args[0]) for call in db.scalars.call_args_list]
    assert all(query.startswith("SELECT ") and "user_id" in query for query in queries)
    # Count is intentionally not hardcoded; load_snapshot may grow new user-scoped queries.


def test_first_unread_position_skips_read_and_skipped_entries() -> None:
    """The census frontier matches unread/unskipped List entries, not raw order."""
    owner = 9
    custom_list = CustomCBLList(id=1, user_id=owner, name="Frontier")
    plan = ContinuityPlan(id=2, user_id=owner, name="Frontier", nodes_json=[])
    entries = [
        CustomCBLEntry(id=1, list_id=1, issue_id=10, position=0, skipped=True),
        CustomCBLEntry(id=2, list_id=1, issue_id=11, position=1, skipped=False),
        CustomCBLEntry(id=3, list_id=1, issue_id=12, position=2, skipped=False),
    ]
    issues = [
        Issue(id=10, thread_id=1, issue_number="1", position=1, status="unread"),
        Issue(id=11, thread_id=1, issue_number="2", position=2, status="read"),
        Issue(id=12, thread_id=1, issue_number="3", position=3, status="unread"),
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    rows = reconcile(
        Snapshot([custom_list], entries, [plan], [], [source], issues=issues), owner
    )["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["first_unread_position"] == 2


def test_unpaired_plan_preserves_all_evidence() -> None:
    """Orphan plans retain JSON-only issues, skips, malformed nodes and placements."""
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Orphan",
        nodes_json=[
            {"node_type": "issue", "ref_id": 99, "optional": True},
            {"node_type": "issue", "ref_id": "bad"},
        ],
    )
    issue = ReadingPlanIssue(
        plan_id=2,
        occurrence_id="skipped",
        issue_id=10,
        lane_id="main",
        display_position=4,
        reader_optional=True,
        reader_role="optional",
        source_metadata_json={"skip": True},
    )
    source = ReadingPlanSource(
        id=3, plan_id=2, raw_source_path="orphan.cbl", metadata_json={"excluded": [20]}
    )
    placement = ReadingPlanSourcePlacement(
        id=4, plan_id=2, occurrence_id="skipped", plan_source_id=3, source_position=42
    )
    rows = reconcile(Snapshot([], [], [plan], [issue], [source], [placement]), 9)["unpaired_plans"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    row = rows[0]
    assert row["plan_nodes"] == plan.nodes_json
    assert row["durable_list_link_ids"] == []
    assert row["issues"] == [
        {
            "issue_id": 10,
            "occurrence_id": "skipped",
            "lane_id": "main",
            "position": 4,
            "is_checkpoint": None,
            "reader_optional": True,
            "reader_role": "optional",
            "source_metadata": {"skip": True},
        }
    ]
    assert row["plan_optional_or_skipped_evidence"] == row["issues"]
    assert row["source_placements"] == [
        {"occurrence_id": "skipped", "source_id": 3, "source_position": 42}
    ]
    assert row["sources"][0]["metadata"] == {"excluded": [20]}
    assert row["malformed_plan_nodes"] == [
        {"index": 1, "node": {"node_type": "issue", "ref_id": "bad"}}
    ]
    assert row["anomalies"] == [
        "malformed_plan_nodes",
        "plan_json_membership_mismatch",
        "unclassified_skip_exclusion_evidence",
    ]
    assert row["resolution"] == "unresolved"


def test_report_materializes_before_persistent_rows_expire(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise report's session lifecycle with persisted ORM state, without a database.

    Attach detached persisted rows to a real SQLAlchemy identity map; transaction
    exit expires them and session exit detaches them, reproducing commit behavior.
    """
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator

    from sqlalchemy.orm import Session, make_transient_to_detached

    plan = ContinuityPlan(id=2, user_id=9, name="Persisted", nodes_json=[], lanes_json=[])
    make_transient_to_detached(plan)
    orm_session = Session()
    orm_session.add(plan)
    engine = SimpleNamespace(dispose=AsyncMock())

    class ReportSession:
        async def __aenter__(self) -> ReportSession:
            return self

        async def __aexit__(self, *args: object) -> None:
            orm_session.close()

        @asynccontextmanager
        async def begin(self) -> AsyncIterator[None]:
            yield
            orm_session.expire_all()

        async def execute(self, statement: object) -> None:
            assert str(statement) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"

    async def snapshot(db: object, user_id: int) -> Snapshot:
        assert user_id == 9
        return Snapshot([], [], [plan], [], [])

    monkeypatch.setattr(census, "create_async_engine", lambda url: engine)
    monkeypatch.setattr(census, "AsyncSession", lambda engine: ReportSession())
    monkeypatch.setattr(census, "load_snapshot", snapshot)
    result = asyncio.run(census.report("postgresql+asyncpg://unused", 9))
    rows = result["unpaired_plans"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["plan_name"] == "Persisted"
    engine.dispose.assert_awaited_once()


def test_json_is_deterministic_and_shared_occurrences_are_preserved() -> None:
    """Database row order never changes JSON or hides shared occurrence identities."""
    import json

    custom_list = CustomCBLList(id=1, user_id=9, name="Ordered")
    entries = [CustomCBLEntry(id=i, list_id=1, issue_id=i, position=i) for i in (1, 2)]
    plan = ContinuityPlan(
        id=2,
        user_id=9,
        name="Ordered",
        nodes_json=[{"node_type": "issue", "ref_id": i} for i in (1, 2)],
    )
    issues = [
        ReadingPlanIssue(
            plan_id=2, occurrence_id=str(i), issue_id=i, lane_id="main", display_position=i
        )
        for i in (1, 2)
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    first = reconcile(Snapshot([custom_list], entries, [plan], issues, [source]), 9)
    second = reconcile(Snapshot([custom_list], entries[::-1], [plan], issues[::-1], [source]), 9)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    rows = first["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert [row["occurrence_id"] for row in rows[0]["plan_issues"]] == ["1", "2"]


def test_fresh_process_registers_cli_models() -> None:
    """Production imports configure ORM without test-only registration."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.report_custom_cbl_plan_reconciliation "
            "import CustomCBLList; CustomCBLList(id=1, user_id=9, name='Fresh')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field,value", [("position", 2), ("lane_id", "other")])
def test_json_placement_conflict(field: str, value: object) -> None:
    """Matching memberships cannot hide conflicting JSON lane or order."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Conflict")
    entries = [CustomCBLEntry(id=i, list_id=1, issue_id=i, position=i) for i in (1, 2)]
    nodes = [{"node_type": "issue", "ref_id": i, "lane_id": "main", "position": i} for i in (1, 2)]
    nodes[0][field] = value
    if field == "position":
        nodes[1][field] = 1
    plan = ContinuityPlan(id=2, user_id=9, name="Conflict", nodes_json=nodes)
    issues = [
        ReadingPlanIssue(
            plan_id=2, occurrence_id=str(i), issue_id=i, lane_id="main", display_position=i
        )
        for i in (1, 2)
    ]
    source = ReadingPlanSource(id=3, plan_id=2, custom_cbl_list_id=1)
    rows = reconcile(Snapshot([custom_list], entries, [plan], issues, [source]), 9)["lists"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    row = rows[0]
    assert row["order_conflict"] is False
    assert row["position_conflicts"] == []
    assert row["plan_json_position_conflicts"]
    assert "plan_json_membership_position_conflict" in row["anomalies"]
    assert row["resolution"] == "unresolved"


@pytest.mark.parametrize("pairing", ["paired", "ambiguous", "unpaired"])
def test_empty_declared_lane_retains_provenance(pairing: str) -> None:
    """Every pairing path preserves empty lanes and their provenance."""
    lists = [] if pairing == "unpaired" else [CustomCBLList(id=1, user_id=9, name="List")]
    if pairing == "ambiguous":
        lists.append(CustomCBLList(id=2, user_id=9, name="Other"))
    lanes = [
        {
            "id": "extra",
            "name": "Empty",
            "order": 1,
            "migration_contract": {"kind": "explicit_reader_order"},
        }
    ]
    plan = ContinuityPlan(id=3, user_id=9, name="Plan", nodes_json=[], lanes_json=lanes)
    sources = [ReadingPlanSource(id=row.id, plan_id=3, custom_cbl_list_id=row.id) for row in lists]
    result = reconcile(Snapshot(lists, [], [plan], [], sources), 9)
    rows = result["unpaired_plans"] if pairing == "unpaired" else result["lists"]
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        assert row["plan_lanes"] == lanes
        assert row["declared_lanes_without_memberships"] == ["extra"]
        assert "declared_lanes_without_memberships" in row["anomalies"]
        assert row["resolution"] == "unresolved"


@pytest.mark.parametrize("pairing", ["paired", "ambiguous", "unpaired"])
@pytest.mark.parametrize("evidence", ["reader_role", "reader_optional", "checkpoint"])
def test_plan_intent_evidence_is_never_aligned(
    pairing: str, evidence: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON-only reader flags and membership-only checkpoints survive every report path."""
    lists = [] if pairing == "unpaired" else [CustomCBLList(id=1, user_id=9, name="List")]
    if pairing == "ambiguous":
        lists.append(CustomCBLList(id=2, user_id=9, name="Other"))
    entries = [
        CustomCBLEntry(id=row.id, list_id=row.id, issue_id=10, position=1, is_checkpoint=False)
        for row in lists
    ]
    node: dict[str, object] = {"node_type": "issue", "ref_id": 10}
    if evidence != "checkpoint":
        node[evidence] = "skipped/excluded" if evidence == "reader_role" else True
    plan = ContinuityPlan(id=3, user_id=9, name="Plan", nodes_json=[node], lanes_json=[])
    issue = ReadingPlanIssue(
        plan_id=3,
        occurrence_id="a",
        issue_id=10,
        lane_id="main",
        display_position=1,
        is_checkpoint=evidence == "checkpoint",
    )
    sources = [ReadingPlanSource(id=row.id, plan_id=3, custom_cbl_list_id=row.id) for row in lists]
    result = reconcile(Snapshot(lists, entries, [plan], [issue], sources), 9)
    rows = result["unpaired_plans"] if pairing == "unpaired" else result["lists"]
    assert isinstance(rows, list) and rows
    for row in rows:
        assert isinstance(row, dict)
        assert row["resolution"] == "unresolved"
        if evidence == "checkpoint":
            members = row["issues"] if pairing == "unpaired" else row["plan_issues"]
            assert members[0]["is_checkpoint"] is True
            assert "unclassified_plan_checkpoint_evidence" in row["anomalies"]
        else:
            assert row["plan_json_optional_or_skipped_evidence"] == [{"index": 0, "node": node}]
            assert "unclassified_plan_json_skip_exclusion_evidence" in row["anomalies"]
    monkeypatch.setattr(census, "report", AsyncMock(return_value=result))
    monkeypatch.setattr(
        sys, "argv", ["census", "--database-url", "unused", "--user-id", "9", "--summary"]
    )
    census.main()
    summary = capsys.readouterr().out
    if evidence == "checkpoint":
        assert '"is_checkpoint": true' in summary
    else:
        assert "plan_json_optional_or_skipped_evidence" in summary
        assert evidence in summary


@pytest.mark.parametrize("pairing", ["paired", "ambiguous", "unpaired"])
def test_list_intent_fields_are_preserved(pairing: str) -> None:
    """The additive Option E fields remain visible without filtering skipped issues."""
    custom_list = CustomCBLList(id=1, user_id=9, name="Intent", mode="strict")
    entry = CustomCBLEntry(id=1, list_id=1, issue_id=10, position=1, gate="hold", skipped=True)
    plans = (
        []
        if pairing == "unpaired"
        else [ContinuityPlan(id=2, user_id=9, name="Plan", nodes_json=[], lanes_json=[])]
    )
    if pairing == "ambiguous":
        plans.append(ContinuityPlan(id=3, user_id=9, name="Other", nodes_json=[], lanes_json=[]))
    sources = [ReadingPlanSource(id=p.id, plan_id=p.id, custom_cbl_list_id=1) for p in plans]
    result = reconcile(Snapshot([custom_list], [entry], plans, [], sources), 9)
    rows = result["lists"]
    assert isinstance(rows, list) and rows
    for row in rows:
        assert row["list_mode"] == "strict"
        entries = row["entries"] if pairing == "unpaired" else row["list_entries"]
        assert entries[0]["gate"] == "hold"
        assert entries[0]["skipped"] is True
        assert entries[0]["issue_id"] == 10
        assert row["resolution"] == "unresolved"
