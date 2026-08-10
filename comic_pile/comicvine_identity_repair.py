"""Confidence-aware ComicVine identity repair and candidate selection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

AUTO_CONFIRM_THRESHOLD = 0.78
AUTO_CONFIRM_MARGIN = 0.12


@dataclass(frozen=True)
class ComicVineRepairContext:
    """ComicPile-side evidence used to evaluate one issue candidate."""

    title: str
    issue_label: str
    publisher: str | None = None
    start_year: int | None = None
    previous_issue_label: str | None = None
    next_issue_label: str | None = None
    repeated_cbl_count: int = 0
    snapshot_synced_at: datetime | None = None
    issue_expected_after: date | None = None


@dataclass(frozen=True)
class ComicVineCandidate:
    """Locally validated ComicVine issue/volume evidence for one candidate mapping."""

    issue_id: int
    volume_id: int
    volume_name: str
    issue_number: str | None
    issue_name: str | None = None
    publisher: str | None = None
    start_year: int | None = None
    previous_issue_exists: bool = False
    next_issue_exists: bool = False
    source: str = "comicvine-local-sqlite"
    segment_start: str | None = None
    segment_end: str | None = None


@dataclass(frozen=True)
class CandidateScore:
    """Deterministic candidate score with human-readable evidence."""

    candidate: ComicVineCandidate
    score: float
    evidence: tuple[str, ...]
    rejection_reason: str | None
    stale_snapshot: bool


@dataclass(frozen=True)
class RepairDecision:
    """Resolution decision that never promotes an ambiguous candidate silently."""

    status: str
    winner: CandidateScore | None
    candidates: tuple[CandidateScore, ...]
    reason: str
    rejected: tuple[CandidateScore, ...] = ()


def normalize_title(value: str) -> str:
    """Normalize a title for comparison while retaining caller-owned original strings."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def normalize_issue_label(value: str | None) -> str:
    """Normalize issue numbers or human labels without assuming numeric-only issues."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = normalized.removeprefix("#").strip()
    return " ".join(normalized.split())


def _snapshot_is_stale(context: ComicVineRepairContext) -> bool:
    if context.snapshot_synced_at is None or context.issue_expected_after is None:
        return False
    return context.issue_expected_after > context.snapshot_synced_at.date()


def score_candidate(context: ComicVineRepairContext, candidate: ComicVineCandidate) -> CandidateScore:
    """Score one issue-level candidate from locally validated evidence."""
    evidence: list[str] = []
    score = 0.0
    expected_issue = normalize_issue_label(context.issue_label)
    candidate_number = normalize_issue_label(candidate.issue_number)
    candidate_name = normalize_issue_label(candidate.issue_name)
    number_match = bool(expected_issue and candidate_number) and candidate_number == expected_issue
    name_match = bool(expected_issue and candidate_name) and candidate_name == expected_issue
    stale_snapshot = _snapshot_is_stale(context)

    if not number_match and not name_match:
        reason = "candidate volume does not contain the ComicPile issue number or issue name"
        if stale_snapshot:
            reason = "local snapshot predates the expected issue; preserve unresolved for live refresh"
        return CandidateScore(candidate, 0.0, ("issue existence not validated",), reason, stale_snapshot)

    if number_match:
        score += 0.34
        evidence.append("issue number matches")
    if name_match:
        score += 0.34
        evidence.append("issue name matches human label")
    if normalize_title(context.title) == normalize_title(candidate.volume_name):
        score += 0.22
        evidence.append("normalized title matches")
    else:
        evidence.append("normalized title differs")
    if context.publisher and candidate.publisher:
        if normalize_title(context.publisher) == normalize_title(candidate.publisher):
            score += 0.12
            evidence.append("publisher matches")
        else:
            score -= 0.18
            evidence.append("publisher conflicts")
    if context.start_year is not None and candidate.start_year is not None:
        if context.start_year == candidate.start_year:
            score += 0.1
            evidence.append("start year matches")
        elif abs(context.start_year - candidate.start_year) <= 1:
            score += 0.04
            evidence.append("start year is adjacent")
        else:
            score -= 0.1
            evidence.append("start year conflicts")
    if context.previous_issue_label and candidate.previous_issue_exists:
        score += 0.06
        evidence.append("previous neighboring issue exists")
    if context.next_issue_label and candidate.next_issue_exists:
        score += 0.06
        evidence.append("next neighboring issue exists")
    if context.repeated_cbl_count > 0:
        bonus = min(context.repeated_cbl_count, 3) * 0.04
        score += bonus
        evidence.append(f"supported by {context.repeated_cbl_count} distinct CBL observation(s)")
    if stale_snapshot:
        evidence.append("local snapshot predates expected issue")

    return CandidateScore(candidate, max(0.0, min(1.0, round(score, 4))), tuple(evidence), None, stale_snapshot)


def decide_candidates(
    scores: list[CandidateScore],
    *,
    existing_confirmed_issue_id: int | None = None,
    embedded_cbl_issue_id: int | None = None,
) -> RepairDecision:
    """Choose a safe mapping state from scored candidates and stronger identity evidence."""
    usable = tuple(sorted((s for s in scores if s.rejection_reason is None), key=lambda s: (-s.score, s.candidate.issue_id)))
    rejected = tuple(sorted((s for s in scores if s.rejection_reason is not None), key=lambda s: s.candidate.issue_id))

    if embedded_cbl_issue_id is not None:
        winner = next((s for s in usable if s.candidate.issue_id == embedded_cbl_issue_id), None)
        if winner is not None:
            return RepairDecision("confirmed", winner, usable, "exact embedded CBL ComicVine issue ID validated against candidate evidence", rejected)
    if existing_confirmed_issue_id is not None:
        winner = next((s for s in usable if s.candidate.issue_id == existing_confirmed_issue_id), None)
        return RepairDecision("confirmed", winner, usable, "preserved existing confirmed ComicVine issue mapping", rejected)
    if not usable:
        reason = "no validated local candidate; snapshot may be stale, so live refresh is required" if any(s.stale_snapshot for s in scores) else "no validated ComicVine candidate"
        return RepairDecision("unresolved", None, (), reason, rejected)

    best = usable[0]
    runner_up = usable[1] if len(usable) > 1 else None
    margin = best.score - runner_up.score if runner_up is not None else best.score
    if best.score >= AUTO_CONFIRM_THRESHOLD and margin >= AUTO_CONFIRM_MARGIN:
        return RepairDecision("confirmed", best, usable, "top locally validated candidate is strong and unambiguous", rejected)
    return RepairDecision("candidate", None, usable, "multiple or insufficiently strong candidates require explicit review", rejected)
