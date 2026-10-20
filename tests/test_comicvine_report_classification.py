"""Tests for stable machine-readable ComicVine hydration classifications."""

import pytest

from comic_pile.comicvine_report_classification import (
    REPORT_CLASSIFICATIONS,
    HydrationReport,
    classify_hydration_report,
)


def _classification_counts(report: HydrationReport) -> dict[str, int]:
    """Return the validated classification counters from a normalized report."""
    raw_counts = report["summary"].get("classifications")
    if not isinstance(raw_counts, dict):
        raise AssertionError("the normalized summary must carry classification counters")
    counts: dict[str, int] = {}
    for name, value in raw_counts.items():
        if not isinstance(value, int):
            raise AssertionError(f"classification counter {name!r} must be an int")
        counts[str(name)] = value
    return counts


def test_classifies_local_first_outcomes_and_emits_full_vocabulary() -> None:
    """Base hydrator states become operator-facing completion/freshness outcomes."""
    report = classify_hydration_report(
        {
            "summary": {"total": 3, "matched": 1, "local-miss": 1, "unresolved": 1},
            "issues": [
                {"issue_id": 1, "status": "matched"},
                {"issue_id": 2, "status": "local-miss"},
                {"issue_id": 3, "status": "unresolved"},
            ],
        }
    )

    assert [row["classification"] for row in report["issues"]] == [
        "completed",
        "stale-source",
        "unresolved",
    ]
    counts = _classification_counts(report)
    assert set(counts) == set(REPORT_CLASSIFICATIONS)
    assert counts["completed"] == 1
    assert counts["stale-source"] == 1
    assert counts["unresolved"] == 1
    assert counts["ambiguous"] == counts["anomalous"] == counts["failed"] == 0


def test_preserves_explicit_discovery_classification() -> None:
    """Later discovery stages can report ambiguity/anomalies without being overwritten."""
    report = classify_hydration_report(
        {
            "issues": [
                {"issue_id": 1, "status": "unresolved", "classification": "ambiguous"},
                {"issue_id": 2, "status": "unresolved", "classification": "anomalous"},
                {"issue_id": 3, "status": "unresolved", "classification": "skipped"},
            ]
        }
    )

    counts = _classification_counts(report)
    assert counts["ambiguous"] == 1
    assert counts["anomalous"] == 1
    assert counts["skipped"] == 1


def test_rejects_unknown_explicit_classification() -> None:
    """Typos cannot silently create an uncounted report category."""
    with pytest.raises(ValueError, match="unknown hydration classification"):
        classify_hydration_report(
            {"issues": [{"issue_id": 1, "status": "unresolved", "classification": "maybe"}]}
        )


def test_rejects_malformed_issue_rows() -> None:
    """Machine-readable reports fail clearly instead of emitting a partial shape."""
    with pytest.raises(ValueError, match="issue rows must be objects"):
        classify_hydration_report({"issues": ["bad-row"]})
