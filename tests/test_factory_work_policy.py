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
    branch: str | None = None,
    body: str | None = None,
) -> dict[str, object]:
    """Build a canonical fixed-model PR linked to one issue."""
    return {
        "number": number,
        "state": state,
        "isDraft": draft,
        "labels": [{"name": label} for label in labels],
        "headRefName": branch or f"factory/18-{issue}-nvidia",
        "body": body or "Worker: opencode-free-model-factory-18",
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


def test_human_pr_with_closing_reference_suppresses_fresh_implementation():
    """A human-authored open PR that closes an issue owns it for intake."""
    issue = issue_fixture(2127)
    human = pr_fixture(
        number=2161,
        issue=2127,
        labels=["factory", "factory:unowned"],
        branch="local/2127-cbl-commit",
        body="Closes #2127",
    )

    candidates = policy.build_candidates([issue], [human])

    assert all(candidate.number != 2127 or candidate.kind != "issue" for candidate in candidates)
    assert candidates == []


def test_non_factory_branch_with_closing_reference_is_recognized():
    """non-`factory/*` branches suppress when they explicitly close the issue."""
    issue = issue_fixture(2127)
    human = pr_fixture(
        number=2161,
        issue=2127,
        labels=["factory", "factory:unowned"],
        branch="local/2127-cbl-commit",
        body="Resolves #2127",
    )

    assert policy._linked_issue_from_pr(human) == 2127
    assert policy.pr_suppresses_issue_candidate(human, {})

    candidates = policy.build_candidates([issue], [human])

    assert all(candidate.number != 2127 or candidate.kind != "issue" for candidate in candidates)


def test_factory_canonical_pr_is_still_recognized_as_suppressing():
    """Factory-authored canonical PRs keep suppressing without a closing body."""
    issue = issue_fixture(2127)
    factory_pr = pr_fixture(
        number=2162,
        issue=2127,
        labels=["factory", "factory:unowned", "factory:review"],
    )

    assert policy._linked_issue_from_pr(factory_pr) == 2127
    assert policy.pr_suppresses_issue_candidate(factory_pr, {})

    candidates = policy.build_candidates([issue], [factory_pr])

    assert all(candidate.number != 2127 or candidate.kind != "issue" for candidate in candidates)


def test_mention_without_closing_reference_does_not_suppress():
    """A stacked/child PR that only mentions #N stays non-canonical."""
    issue = issue_fixture(2127)
    stacked = pr_fixture(
        number=2171,
        issue=2127,
        labels=["factory", "factory:unowned"],
        branch="local/2127-stacked-child",
        body="Depends on #2127",
    )

    assert policy._linked_issue_from_pr(stacked) is None
    assert not policy.pr_suppresses_issue_candidate(stacked, {})

    candidates = policy.build_candidates([issue], [stacked])

    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 2127)
    ]


def test_closed_human_pr_no_longer_suppresses_fresh_implementation():
    """A closed/superseded human PR releases its issue for new implementation."""
    issue = issue_fixture(2127)
    closed = pr_fixture(
        number=2161,
        issue=2127,
        labels=["factory", "factory:unowned"],
        state="CLOSED",
        branch="local/2127-cbl-commit",
        body="Closes #2127",
    )

    candidates = policy.build_candidates([issue], [closed])

    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 2127)
    ]


def test_draft_pr_with_closing_reference_does_not_suppress():
    """Only open non-draft PRs claim ownership via a closing reference."""
    issue = issue_fixture(2127)
    draft = pr_fixture(
        number=2161,
        issue=2127,
        labels=["factory", "factory:unowned"],
        draft=True,
        branch="local/2127-cbl-commit",
        body="Closes #2127",
    )

    assert policy._linked_issue_from_pr(draft) == 2127
    assert not policy.pr_suppresses_issue_candidate(draft, {})

    candidates = policy.build_candidates([issue], [draft])

    assert [(candidate.kind, candidate.number) for candidate in candidates] == [
        ("issue", 2127)
    ]


def test_two_open_implementation_prs_cannot_open_a_third():
    """Concurrent open implementation PRs block further fresh intake."""
    issue = issue_fixture(2127)
    human = pr_fixture(
        number=2161,
        issue=2127,
        labels=["factory", "factory:unowned"],
        branch="local/2127-cbl-commit",
        body="Resolves #2127",
    )
    duplicate = pr_fixture(
        number=2162,
        issue=2127,
        labels=["factory", "factory:17", "factory:review"],
    )

    candidates = policy.build_candidates([issue], [human, duplicate])

    assert all(candidate.number != 2127 or candidate.kind != "issue" for candidate in candidates)


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
