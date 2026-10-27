"""Detect future unread order gaps using the canonical graph validator.

An empty Option E migration manifest is not evidence that these gaps are gone.
This module is pure, read-only and never promotes historical dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.services.reading_effective_snapshot import effective_reading_snapshot
from app.services.reading_list_cycle_validator import (
    ReadingCycleError,
    validate_reading_constraints,
)
from app.services.reading_list_evaluator import ReadingPrerequisite, ReadingSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalEdge:
    """One historical Issue-to-Issue relationship that might remain relevant."""
    dependency_id: int
    source_issue_id: int
    target_issue_id: int
    origin: str | None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class FutureParity:
    """Audited relations that are implied or missing in canonical execution."""
    examined: int
    implied: int
    missing: tuple[HistoricalEdge, ...]
    excluded: tuple[HistoricalEdge, ...] = ()
    contradicted: tuple[HistoricalEdge, ...] = ()

    @property
    def safe_to_certify(self) -> bool:
        """False for missing requirements or reversed historical constraints."""
        return not self.missing and not self.contradicted


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
    effective = effective_reading_snapshot(snapshot)
    validate_reading_constraints(effective)
    available = {issue.issue_id for issue in snapshot.issues}
    existing = {p.prerequisite_id for p in effective.prerequisites}
    missing: list[HistoricalEdge] = []
    excluded: list[HistoricalEdge] = []
    contradicted: list[HistoricalEdge] = []
    implied = 0
    for old in historical_edges:
        if old.source_issue_id not in available or old.target_issue_id not in available:
            raise ValueError("Historical edge references a foreign/missing Issue")
        if (old.source_issue_id in snapshot.excluded_issue_ids
                or old.target_issue_id in snapshot.excluded_issue_ids):
            excluded.append(old)
            continue
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
            effective, prerequisites=(*effective.prerequisites, reverse),
        )
        try:
            validate_reading_constraints(trial)
        except ReadingCycleError:
            implied += 1
        else:
            forward = ReadingPrerequisite(
                synthetic_id, old.source_issue_id, old.target_issue_id, "reader",
            )
            trial_forward = replace(
                effective, prerequisites=(*effective.prerequisites, forward),
            )
            try:
                validate_reading_constraints(trial_forward)
            except ReadingCycleError:
                # The canonical reader-owned sequence goes the opposite way.
                # Never promote a stale compiled edge against that sequence.
                contradicted.append(old)
            else:
                missing.append(old)
    return FutureParity(
        len(historical_edges), implied, tuple(missing), tuple(excluded),
        tuple(contradicted),
    )
