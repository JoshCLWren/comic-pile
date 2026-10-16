"""Shadow eligibility compares complete scalar evidence without repairing the reader."""

from dataclasses import replace

import pytest

from app.repositories.reading_shadow_repository import (
    ShadowReadingInputs,
    StoredThreadEligibility,
    UnresolvedReadingReference,
)
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingPrerequisite,
    ReadingThread,
)
from app.services.reading_shadow_service import compare_reading_eligibility


def _inputs(
    count: int = 3,
) -> ShadowReadingInputs:
    """Make independent active series so list constraints can change offers."""
    return ShadowReadingInputs(
        user_id=1,
        threads=tuple(ReadingThread(i) for i in range(1, count + 1)),
        issues=tuple(ReadingIssue(i * 10, i, 1) for i in range(1, count + 1)),
        lists=(),
        prerequisites=(),
        excluded_issue_ids=frozenset(),
        stored=tuple(StoredThreadEligibility(i, i * 10, False, i) for i in range(1, count + 1)),
        unresolved=(),
        inert_dependency_count=0,
    )


def _rows(report: dict[str, object]) -> list[dict[str, object]]:
    """Narrow JSON output for assertions without suppressing typing."""
    rows = report["threads"]
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    return rows


def test_24_stale_frontiers_and_empty_shell_are_all_diagnostic() -> None:
    """Every pointer mismatch is counted, even outside the emitted detail limit."""
    inputs = _inputs(24)
    inputs = replace(
        inputs, stored=tuple(replace(row, next_issue_id=None) for row in inputs.stored)
    )
    report = compare_reading_eligibility(inputs, max_threads=5)
    assert report["summary"] == {
        "threads": 24,
        "active_threads": 24,
        "issues": 24,
        "lists": 0,
        "list_entries": 0,
        "prerequisites": 0,
        "inert_dependencies": 0,
        "excluded_issues": 0,
        "frontier_divergences": 24,
        "cache_divergences": 0,
        "eligibility_divergences": 0,
    }
    assert report["threads_truncated"] is True
    assert len(_rows(report)) == 5
    assert all(row["frontier_divergence"] for row in _rows(report))
    shell = replace(_inputs(1), issues=())
    row = _rows(compare_reading_eligibility(shell))[0]
    assert row["current_pool_candidate"] is True
    assert row["proposed_eligible"] is False
    assert row["stored_pointer_in_thread"] is False
    assert row["stored_next_issue_id"] is None


def test_strict_list_hold_skip_and_bounded_blocker_identity() -> None:
    """Inactive list intent is hypothetical; strict/hold causes are both retained."""
    inputs = replace(
        _inputs(),
        lists=(
            ReadingList(
                7,
                "strict",
                (
                    ReadingListEntry(10),
                    ReadingListEntry(20, gate="hold"),
                    ReadingListEntry(30),
                ),
            ),
        ),
    )
    report = compare_reading_eligibility(inputs, max_blockers=1)
    first, milestone, after = _rows(report)
    assert first["proposed_eligible"] is True
    assert milestone["proposed_eligible"] is False
    assert after["blocker_count"] == 2
    assert after["blockers_truncated"] is True
    assert report["valid"] is True
    assert inputs.lists[0].mode == "strict"
    loose = replace(
        inputs,
        lists=(
            ReadingList(
                7,
                "loose",
                (
                    ReadingListEntry(10, skipped=True),
                    ReadingListEntry(20, gate="hold"),
                    ReadingListEntry(30),
                ),
            ),
        ),
    )
    a, b, c = _rows(compare_reading_eligibility(loose))
    assert a["proposed_eligible"] is True  # Skip is list-local.
    assert b["proposed_eligible"] is True
    assert c["proposed_eligible"] is False  # Unread milestone continues holding.


def test_starman_prerequisite_survives_list_edits_and_cache_drift() -> None:
    """Stable 26360 -> 117189 blocks JSA independently of any list copy."""
    inputs = replace(
        _inputs(2),
        issues=(ReadingIssue(26360, 1, 1), ReadingIssue(117189, 2, 1)),
        prerequisites=(
            ReadingPrerequisite(44, 26360, 117189, "converted", ("private historical note",)),
        ),
        stored=(
            StoredThreadEligibility(1, 26360, False, 1),
            StoredThreadEligibility(2, 117189, False, 2),
        ),
    )
    report = compare_reading_eligibility(inputs)
    row = _rows(report)[1]
    assert row["cache_divergence"] is True
    assert row["proposed_eligible"] is False
    blockers = row["blockers"]
    assert isinstance(blockers, list)
    assert blockers[0]["waiting_on_issue_ids"] == (26360,)
    assert blockers[0]["prerequisite_id"] == 44
    assert blockers[0]["origin"] == "converted"
    assert "private historical note" not in str(report)
    assert compare_reading_eligibility(replace(inputs, lists=())) == report


def test_bad_references_cycles_and_exclusions_never_claim_parity() -> None:
    """Incomplete/invalid graphs fail closed without silently dropping blockers."""
    inputs = _inputs()
    unresolved = replace(inputs, unresolved=(UnresolvedReadingReference("prerequisite", 77),))
    result = compare_reading_eligibility(unresolved)
    assert result["valid"] is False
    assert all(row["proposed_eligible"] is None for row in _rows(result))
    cycle = replace(
        inputs,
        prerequisites=(
            ReadingPrerequisite(1, 10, 20),
            ReadingPrerequisite(2, 20, 30),
            ReadingPrerequisite(3, 30, 10),
        ),
    )
    result = compare_reading_eligibility(cycle)
    assert result["valid"] is False
    assert "reading_cycle" in str(result["diagnostics"])
    stranded = replace(
        inputs, prerequisites=(ReadingPrerequisite(1, 10, 20),), excluded_issue_ids=frozenset({10})
    )
    result = compare_reading_eligibility(stranded)
    assert result["valid"] is False
    assert "invalid_snapshot" in str(result["diagnostics"])
    excluded = replace(inputs, excluded_issue_ids=frozenset({10}))
    assert _rows(compare_reading_eligibility(excluded))[0]["proposed_eligible"] is False


def test_legacy_stored_and_derived_frontier_drift_are_separate() -> None:
    """A stale pointer can conceal a real blocker at an earlier unread issue."""
    inputs = replace(
        _inputs(2),
        issues=(ReadingIssue(10, 1, 1), ReadingIssue(20, 2, 1), ReadingIssue(21, 2, 2)),
        stored=(StoredThreadEligibility(1, 10, False, 1), StoredThreadEligibility(2, 21, False, 2)),
        prerequisites=(ReadingPrerequisite(1, 10, 20),),
    )
    row = _rows(compare_reading_eligibility(inputs))[1]
    assert row["legacy_stored_frontier_blocked"] is False
    assert row["legacy_derived_frontier_blocked"] is True
    assert row["derived_next_issue_id"] == 20
    assert row["eligibility_divergence"] is True


@pytest.mark.parametrize("limit", [0, -1])
def test_report_limits_must_be_positive(limit: int) -> None:
    """A zero detail limit cannot silently hide all diagnostics."""
    with pytest.raises(ValueError, match="positive"):
        compare_reading_eligibility(_inputs(), max_threads=limit)


def test_inactive_frontier_defects_remain_visible_without_an_offer() -> None:
    """The frontier census must not lose completed or snoozed historical defects."""
    inputs = replace(
        _inputs(1),
        threads=(ReadingThread(1, "completed"),),
        stored=(StoredThreadEligibility(1, None, False, 1),),
    )
    report = compare_reading_eligibility(inputs)
    row = _rows(report)[0]
    assert row["status"] == "completed"
    assert row["frontier_divergence"] is True
    assert row["current_pool_candidate"] is False
    assert row["proposed_pool_candidate"] is False
    assert row["eligibility_divergence"] is False
