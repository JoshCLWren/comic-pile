"""Normalize ComicVine hydrator outcomes into stable machine-readable classifications."""

from __future__ import annotations

from typing import Any, TypedDict

REPORT_CLASSIFICATIONS = (
    "matched",
    "ambiguous",
    "stale-source",
    "anomalous",
    "unresolved",
    "failed",
    "skipped",
    "completed",
)


class HydrationReport(TypedDict):
    """Normalized hydration report shape used by operators and tests."""

    summary: dict[str, Any]
    issues: list[dict[str, Any]]


def classify_hydration_report(report: dict[str, object]) -> HydrationReport:
    """Add stable outcome classifications without discarding the lower-level status.

    The local-first hydrator can prove three states directly: a complete local match, a
    confirmed identity missing from the snapshot, or an unresolved identity. The first two
    map to ``completed`` and ``stale-source`` respectively. Later discovery stages may set an
    explicit ``classification`` (for example ``ambiguous`` or ``anomalous``); this function
    preserves those values and always emits counters for the complete report vocabulary.
    """
    raw_issues = report.get("issues")
    if not isinstance(raw_issues, list):
        raise ValueError("hydration report issues must be a list")

    counts = dict.fromkeys(REPORT_CLASSIFICATIONS, 0)
    classified: list[dict[str, Any]] = []
    for raw_issue in raw_issues:
        if not isinstance(raw_issue, dict):
            raise ValueError("hydration report issue rows must be objects")
        issue = dict(raw_issue)
        explicit = issue.get("classification")
        if explicit is not None:
            if explicit not in REPORT_CLASSIFICATIONS:
                raise ValueError(f"unknown hydration classification: {explicit}")
            classification = str(explicit)
        else:
            status = issue.get("status")
            if status == "matched":
                classification = "completed"
            elif status == "local-miss":
                classification = "stale-source"
            elif status == "unresolved":
                classification = "unresolved"
            else:
                classification = "failed"
        issue["classification"] = classification
        counts[classification] += 1
        classified.append(issue)

    summary = report.get("summary")
    normalized_summary = dict(summary) if isinstance(summary, dict) else {}
    normalized_summary["classifications"] = counts
    return {"summary": normalized_summary, "issues": classified}
