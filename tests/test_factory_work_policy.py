"""Regression coverage for factory assignment review capacity and independence."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "factory_work_policy",
    SCRIPTS / "factory_work_policy.py",
)
assert SPEC is not None and SPEC.loader is not None
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)

Candidate = policy.Candidate


def candidate(
    *,
    kind: str,
    number: int,
    stage: str | None = None,
    producer: str | None = None,
    lane: int = 3,
) -> Candidate:
    """Build a deterministic candidate fixture."""
    return Candidate(
        kind=kind,
        number=number,
        lane=lane,
        priority=0,
        created_at="2026-08-16T00:00:00Z",
        stage=stage,
        producer_worker=producer,
    )


def issue_fixture(number: int) -> dict[str, object]:
    """Build an unowned issue that would otherwise be executable."""
    return {
        "number": number,
        "state": "OPEN",
        "title": f"Issue {number}",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }


def pr_fixture(
    *,
    number: int,
    issue: int,
    labels: list[str],
    state: str = "OPEN",
    draft: bool = False,
) -> dict[str, object]:
    """Build a canonical fixed-model PR linked to one issue."""
    return {
        "number": number,
        "state": state,
        "isDraft": draft,
        "labels": [{"name": label} for label in labels],
        "headRefName": f"factory/18-{issue}-nvidia",
        "body": "Worker: opencode-free-model-factory-18",
        "createdAt": "2026-08-16T01:00:00Z",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }


def test_producing_worker_cannot_receive_own_semantic_review():
    """Review assignment itself enforces producer/reviewer independence."""
    own_review = candidate(
        kind="pr",
        number=1390,
        stage="factory:review",
        producer="43",
    )
    issue = candidate(kind="issue", number=1500)
    ordered = policy.order_candidates_for_worker([own_review, issue], "43")
    assert own_review not in ordered
    assert ordered == [issue]


def test_producer_can_receive_repair_work_without_self_approving():
    """Independence applies to semantic approval, not ordinary repair."""
    repair = candidate(
        kind="pr",
        number=1390,
        stage="factory:changes-requested",
        producer="43",
    )
    ordered = policy.order_candidates_for_worker([repair], "43")
    assert ordered == [repair]


def test_reserved_review_worker_prefers_factory_review():
    """A stable minority of the fleet gives review dependable capacity."""
    assert policy.review_capacity_worker("6")
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue = candidate(kind="issue", number=1500, lane=1)
    ordered = policy.order_candidates_for_worker([issue, review], "6")
    assert ordered[0] == review


def test_non_reserved_worker_preserves_product_capacity():
    """Ordinary workers keep product implementation moving alongside review."""
    assert not policy.review_capacity_worker("9")
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue = candidate(kind="issue", number=1500, lane=5)
    ordered = policy.order_candidates_for_worker([review, issue], "9")
    assert ordered[0] == issue


def test_stage_precedence_is_deterministic_for_inconsistent_labels():
    """Transient contradictory labels never randomize semantic review classification."""
    labels = {"factory:ci", "factory:review", "factory:building"}
    assert policy.stage_of(labels) == "factory:review"
    assert policy.stage_of(labels) == "factory:review"


def test_shared_producer_provenance_drives_assignment():
    """Assignment derives producer identity through the canonical review policy."""
    pr = {
        "headRefName": "factory/43-1386-opencode-free",
        "body": "Worker: opencode-free-model-factory-17",
    }
    assert policy.producer_worker_from_pr(pr) == "43"


def test_closed_pr_is_never_a_candidate():
    """Autonomous assignment never resurrects a closed PR."""
    pr = {
        "number": 1390,
        "state": "CLOSED",
        "isDraft": False,
        "labels": [
            {"name": "factory"},
            {"name": "factory:unowned"},
            {"name": "factory:review"},
        ],
        "headRefName": "factory/43-1386-opencode-free",
        "body": "Worker: opencode-free-model-factory-43",
        "createdAt": "2026-08-16T00:00:00Z",
    }
    assert not policy.pr_is_static_candidate(pr, {})


def test_open_owned_pr_suppresses_fresh_issue_implementation():
    """An in-flight review lease cannot make its issue reappear as new work."""
    issue = issue_fixture(1487)
    pr = pr_fixture(
        number=1512,
        issue=1487,
        labels=["factory", "factory:18", "factory:review"],
    )

    candidates = policy.build_candidates([issue], [pr])

    assert all(candidate.number != 1487 or candidate.kind != "issue" for candidate in candidates)
    assert candidates == []


def test_open_blocked_or_draft_pr_still_suppresses_duplicate_issue_work():
    """Temporarily ineligible PR states fail closed instead of spawning replacements."""
    issue = issue_fixture(1399)
    blocked = pr_fixture(
        number=1510,
        issue=1399,
        labels=["factory", "factory:unowned", "factory:blocked"],
    )
    draft = pr_fixture(
        number=1510,
        issue=1399,
        labels=["factory", "factory:unowned", "factory:review"],
        draft=True,
    )

    for pr in (blocked, draft):
        candidates = policy.build_candidates([issue], [pr])
        assert all(
            candidate.number != 1399 or candidate.kind != "issue"
            for candidate in candidates
        )


def test_urgent_bug_with_open_blocked_pr_still_has_one_canonical_pr():
    """Urgency never permits a second implementation PR for the same issue."""
    issue = issue_fixture(1882)
    issue["labels"] = [
        {"name": "factory:unowned"},
        {"name": "user-reported"},
        {"name": "bug"},
    ]
    blocked = pr_fixture(
        number=1897,
        issue=1882,
        labels=["factory", "factory:unowned", "factory:blocked"],
    )

    candidates = policy.build_candidates([issue], [blocked])

    assert all(
        candidate.number != 1882 or candidate.kind != "issue"
        for candidate in candidates
    )


def test_closed_pr_releases_issue_back_to_implementation_queue():
    """Closing the canonical PR makes its still-open issue eligible again."""
    issue = issue_fixture(1487)
    closed = pr_fixture(
        number=1512,
        issue=1487,
        labels=["factory", "factory:unowned", "factory:review"],
        state="CLOSED",
    )

    candidates = policy.build_candidates([issue], [closed])

    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 1487)
    ]


def test_plan_distinct_assignments_reserves_review_without_stopping_product():
    """One batch can assign review and implementation concurrently."""
    review = candidate(kind="pr", number=1390, stage="factory:review", producer="43")
    issue_a = candidate(kind="issue", number=1500)
    issue_b = candidate(kind="issue", number=1501)
    assignments = policy.plan_distinct_assignments(
        [review, issue_a, issue_b],
        ["6", "9"],
    )
    assert assignments["6"] == review
    assert assignments["9"].kind == "issue"


# ── parse_depends_on_numbers and body_depends_on_unresolved unit tests ──


def test_parse_depends_on_single_prerequisite():
    """Single 'Depends on #NNN' returns one number."""
    assert policy.parse_depends_on_numbers("Depends on #2126") == {2126}


def test_parse_depends_on_multiple_prerequisites():
    """Comma-separated prerequisites are all extracted."""
    body = "Depends on #2126, #2127, and #2128 being merged"
    assert policy.parse_depends_on_numbers(body) == {2126, 2127, 2128}


def test_parse_depends_on_case_insensitive():
    """Both 'Depends on' and 'depends on' are recognized."""
    assert policy.parse_depends_on_numbers("depends on #42") == {42}


def test_parse_depends_on_casual_mentions_not_matched():
    """Casual '#N' mentions without 'Depends on' prefix are ignored."""
    body = "See also #100 and #200 for context."
    assert policy.parse_depends_on_numbers(body) == set()


def test_parse_depends_on_empty_body():
    """Empty body yields no prerequisites."""
    assert policy.parse_depends_on_numbers("") == set()


def test_body_depends_on_unresolved_true():
    """Declares a prerequisite that is still in the open set."""
    assert policy.body_depends_on_unresolved("Depends on #10", {10, 20}) is True


def test_body_depends_on_unresolved_false_when_resolved():
    """Declares a prerequisite that is not in the open set."""
    assert policy.body_depends_on_unresolved("Depends on #10", {20}) is False


def test_body_depends_on_unresolved_false_no_declaration():
    """No 'Depends on' means no blocking."""
    assert policy.body_depends_on_unresolved("Just a normal issue", {10}) is False


# ── Acceptance criterion 1: single open prerequisite excluded ──


def test_issue_with_one_open_prerequisite_excluded_from_intake():
    """Issue declaring 'Depends on #N' where #N is open is not a candidate."""
    prerequisite = {
        "number": 100,
        "state": "OPEN",
        "title": "Prerequisite",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    child = {
        "number": 200,
        "state": "OPEN",
        "title": "Child",
        "labels": [{"name": "factory:unowned"}],
        "body": "Depends on #100",
        "createdAt": "2026-08-16T01:00:00Z",
    }
    candidates = policy.build_candidates([prerequisite, child], [])
    assert all(c.number != 200 or c.kind != "issue" for c in candidates)


# ── Acceptance criterion 2: multiple prerequisites all must resolve ──


def test_issue_with_multiple_open_prerequisites_blocked_until_all_complete():
    """Issue blocked until every declared prerequisite is resolved."""
    prereq_a = {
        "number": 100,
        "state": "OPEN",
        "title": "Prereq A",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    prereq_b = {
        "number": 101,
        "state": "OPEN",
        "title": "Prereq B",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    child = {
        "number": 200,
        "state": "OPEN",
        "title": "Child",
        "labels": [{"name": "factory:unowned"}],
        "body": "Depends on #100 and #101",
        "createdAt": "2026-08-16T01:00:00Z",
    }
    # Both open — blocked
    candidates = policy.build_candidates([prereq_a, prereq_b, child], [])
    assert all(c.number != 200 or c.kind != "issue" for c in candidates)
    # One closed, one open — still blocked
    prereq_a_closed = {
        **prereq_a,
        "state": "CLOSED",
        "labels": [{"name": "factory:unowned"}, {"name": "ralph-status:done"}],
    }
    candidates = policy.build_candidates([prereq_a_closed, prereq_b, child], [])
    assert all(c.number != 200 or c.kind != "issue" for c in candidates)


# ── Acceptance criterion 3: closing final prerequisite makes child eligible ──


def test_closing_final_prerequisite_makes_child_eligible():
    """When the last prerequisite closes, the child becomes a candidate."""
    prereq = {
        "number": 100,
        "state": "CLOSED",
        "title": "Prereq",
        "labels": [{"name": "factory:unowned"}, {"name": "ralph-status:done"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    child = {
        "number": 200,
        "state": "OPEN",
        "title": "Child",
        "labels": [{"name": "factory:unowned"}],
        "body": "Depends on #100",
        "createdAt": "2026-08-16T01:00:00Z",
    }
    # Only closed prerequisite in the open set — no blocking
    candidates = policy.build_candidates([child], [])
    assert any(c.kind == "issue" and c.number == 200 for c in candidates)


# ── Acceptance criterion 4: casual mentions do not block ──


def test_casual_hash_mentions_do_not_block_intake():
    """Mentions like '#N' without 'Depends on' prefix are not prerequisites."""
    issue = {
        "number": 200,
        "state": "OPEN",
        "title": "Normal issue",
        "labels": [{"name": "factory:unowned"}],
        "body": "Related to #100 but not blocked by it.",
        "createdAt": "2026-08-16T01:00:00Z",
    }
    prerequisite_like = {
        "number": 100,
        "state": "OPEN",
        "title": "Some other issue",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    candidates = policy.build_candidates([prerequisite_like, issue], [])
    assert any(c.kind == "issue" and c.number == 200 for c in candidates)


# ── Acceptance criterion 5: existing canonical PR still repairable ──


def test_existing_pr_still_eligible_even_if_issue_gains_dependency():
    """A canonical PR for an issue can enter repair/review regardless of issue deps."""
    prereq = {
        "number": 100,
        "state": "OPEN",
        "title": "Prereq",
        "labels": [{"name": "factory:unowned"}],
        "createdAt": "2026-08-16T00:00:00Z",
    }
    issue = {
        "number": 200,
        "state": "OPEN",
        "title": "Child",
        "labels": [{"name": "factory:unowned"}],
        "body": "Depends on #100",
        "createdAt": "2026-08-16T01:00:00Z",
    }
    existing_pr = {
        "number": 300,
        "state": "OPEN",
        "isDraft": False,
        "labels": [
            {"name": "factory"},
            {"name": "factory:unowned"},
            {"name": "factory:review"},
        ],
        "headRefName": "factory/42-200-opencode-free",
        "body": "Worker: opencode-free-model-factory-42",
        "createdAt": "2026-08-16T02:00:00Z",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }
    candidates = policy.build_candidates([prereq, issue], [existing_pr])
    pr_candidates = [c for c in candidates if c.kind == "pr"]
    assert any(c.number == 300 for c in pr_candidates)


# ── Acceptance criterion 6: CBL chain represented in policy tests ──


def test_cbl_chain_2126_to_2129_all_open_blocks_youngest():
    """The full CBL dependency chain blocks the last child when all are open."""
    issues = [
        {
            "number": 2126,
            "state": "OPEN",
            "title": "Child A",
            "labels": [{"name": "factory:unowned"}],
            "createdAt": "2026-08-16T00:00:00Z",
        },
        {
            "number": 2127,
            "state": "OPEN",
            "title": "Child B",
            "labels": [{"name": "factory:unowned"}],
            "body": "Depends on #2126",
            "createdAt": "2026-08-16T01:00:00Z",
        },
        {
            "number": 2128,
            "state": "OPEN",
            "title": "Child C",
            "labels": [{"name": "factory:unowned"}],
            "body": "Depends on #2126 and #2127",
            "createdAt": "2026-08-16T02:00:00Z",
        },
        {
            "number": 2129,
            "state": "OPEN",
            "title": "Child D",
            "labels": [{"name": "factory:unowned"}],
            "body": "Depends on #2126, #2127, and #2128",
            "createdAt": "2026-08-16T03:00:00Z",
        },
    ]
    candidates = policy.build_candidates(issues, [])
    candidate_numbers = {c.number for c in candidates}
    # Child A (2126) has no deps — eligible
    assert 2126 in candidate_numbers
    # Children B, C, D have open prerequisites — blocked
    assert 2127 not in candidate_numbers
    assert 2128 not in candidate_numbers
    assert 2129 not in candidate_numbers


def test_cbl_chain_2126_to_2129_closing_a_and_b_unblocks_c():
    """When 2126 and 2127 close, 2128 becomes eligible while 2129 stays blocked."""
    issues = [
        {
            "number": 2126,
            "state": "CLOSED",
            "title": "Child A",
            "labels": [{"name": "ralph-status:done"}],
            "createdAt": "2026-08-16T00:00:00Z",
        },
        {
            "number": 2127,
            "state": "CLOSED",
            "title": "Child B",
            "labels": [{"name": "ralph-status:done"}],
            "createdAt": "2026-08-16T01:00:00Z",
        },
        {
            "number": 2128,
            "state": "OPEN",
            "title": "Child C",
            "labels": [{"name": "factory:unowned"}],
            "body": "Depends on #2126 and #2127",
            "createdAt": "2026-08-16T02:00:00Z",
        },
        {
            "number": 2129,
            "state": "OPEN",
            "title": "Child D",
            "labels": [{"name": "factory:unowned"}],
            "body": "Depends on #2126, #2127, and #2128",
            "createdAt": "2026-08-16T03:00:00Z",
        },
    ]
    candidates = policy.build_candidates(issues, [])
    candidate_numbers = {c.number for c in candidates}
    # 2128 now eligible (both prereqs closed, only child left is open)
    assert 2128 in candidate_numbers
    # 2129 still blocked by open 2128
    assert 2129 not in candidate_numbers
