"""Detect future unread order gaps using the canonical graph validator.

An empty Option E migration manifest is not evidence that these gaps are gone.
This module is pure, read-only and never promotes historical dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import ReadingPrerequisite, ReadingSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalEdge:
    dependency_id: int
    source_issue_id: int
    target_issue_id: int
    origin: str | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class FutureParity:
    examined: int
    implied: int
    missing: tuple[HistoricalEdge, ...]

    @property
    def safe_to_certify(self) -> bool:
        """False unless every reviewed edge follows from the canonical graph."""
        return not self.missing


def audit_future_parity(
    snapshot: ReadingSnapshot, historical_edges: tuple[HistoricalEdge, ...]
) -> FutureParity:
    """Find historical unread requirements absent from the *whole* live graph.

    For source -> target to be implied, adding target -> source must make the
    canonical validator detect a cycle. This asks the actual canonical graph,
    preserving strict overlap exceptions and positional gates, even when the
    target is not the first unread issue in its Thread.
    """
    validate_reading_constraints(snapshot)
    available = {issue.issue_id for issue in snapshot.issues}
    existing = {p.prerequisite_id for p in snapshot.prerequisites}
    missing: list[HistoricalEdge] = []
    implied = 0
    for old in historical_edges:
        if old.source_issue_id not in available or old.target_issue_id not in available:
            raise ValueError("Historical edge references a foreign/missing Issue")
        if old.source_issue_id == old.target_issue_id:
            missing.append(old)
            continue
        synthetic_id = -old.dependency_id
        if synthetic_id in existing:
            raise ValueError("Audit prerequisite ID collision")
        reverse = ReadingPrerequisite(
            synthetic_id, old.target_issue_id, old.source_issue_id, "reader",
        )
        trial = replace(
            snapshot, prerequisites=(*snapshot.prerequisites, reverse),
        )
        try:
            validate_reading_constraints(trial)
        except ReadingCycleError:
            implied += 1
        else:
            missing.append(old)
    return FutureParity(len(historical_edges), implied, tuple(missing))
