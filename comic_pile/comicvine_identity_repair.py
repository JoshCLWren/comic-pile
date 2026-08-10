"""Confidence-aware ComicVine identity repair and candidate selection."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime

AUTO_CONFIRM_THRESHOLD = 0.82
AUTO_CONFIRM_MARGIN = 0.12


@dataclass(frozen=True)
class ComicVineRepairContext:
    """ComicPile-side evidence used to evaluate one issue candidate.

    Args:
        title: Original ComicPile thread/title text.
        issue_label: ComicPile issue number or human label such as ``Revival``.
        publisher: Expected publisher when known.
        start_year: Expected series/segment start year when known.
        previous_issue_label: Neighboring ComicPile issue label before this issue.
        next_issue_label: Neighboring ComicPile issue label after this issue.
        repeated_cbl_count: Number of distinct CBL observations supporting this candidate.
        snapshot_synced_at: Freshness boundary for the local ComicVine snapshot.
        issue_expected_after: Date after which a missing local issue may simply be post-snapshot.
    """

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


def normalize_title(value: str) -> str:
    """Normalize a title for comparison while retaining caller-owned original strings.

    Args:
        value: Source title text.

    Returns:
        Case-folded alphanumeric words with punctuation/spacing normalized.
    """
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", " and ")
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def normalize_issue_label(value: str | None) -> str:
    """Normalize issue numbers or human labels without assuming numeric-only issues.

    Args:
        value: Issue number/name text.

    Returns:
        Comparable normalized text.
    """
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = normalized.removeprefix("#").strip()
    return " ".join(normalized.split())


def _snapshot_is_stale(context: ComicVineRepairContext) -> bool:
    if context.snapshot_synced_at is None or context.issue_expected_after is None:
        return False
    return context.issue_expected_after > context.snapshot_synced_at.date()


def score_candidate(
    context: ComicVineRepairContext,
    candidate: ComicVineCandidate,
) -> CandidateScore:
    """Score one issue-level candidate from locally validated evidence.

    FTS/provider rank is intentionally absent from the inputs. A candidate must contain the
    relevant issue number or issue name before it can receive a usable score.

    Args:
        context: ComicPile-side issue evidence.
        candidate: One ComicVine issue candidate and its volume context.

    Returns:
        Explainable score, rejection reason, and snapshot-staleness marker.
    """
    evidence: list[str] = []
    score = 0.0
    expected_issue = normalize_issue_label(context.issue_label)
    number_match = normalize_issue_label(candidate.issue_number) == expected_issue
    name_match = normalize_issue_label(candidate.issue_name) == expected_issue
    stale_snapshot = _snapshot_is_stale(context)

    if not number_match and not name_match:
        reason = "candidate volume does not contain the ComicPile issue number or issue name"
        if stale_snapshot:
            reason = "local snapshot predates the expected issue; preserve unresolved for live refresh"
        return CandidateScore(
            candidate=candidate,
            score=0.0,
            evidence=("issue existence not validated",),
            rejection_reason=reason,
            stale_snapshot=stale_snapshot,
        )

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

    bounded_score = max(0.0, min(1.0, round(score, 4)))
    return CandidateScore(
        candidate=candidate,
        score=bounded_score,
        evidence=tuple(evidence),
        rejection_reason=None,
        stale_snapshot=stale_snapshot,
    )


def decide_candidates(
    scores: list[CandidateScore],
    *,
    existing_confirmed_issue_id: int | None = None,
    embedded_cbl_issue_id: int | None = None,
) -> RepairDecision:
    """Choose a safe mapping state from scored candidates and stronger identity evidence.

    Resolution order is exact embedded CBL ID, existing confirmed mapping, then scored candidates.
    Scored candidates auto-confirm only when the best candidate is independently strong and clearly
    separated from the runner-up. Otherwise all valid candidates remain reviewable.

    Args:
        scores: Candidate scores from local/live provider evidence.
        existing_confirmed_issue_id: Existing confirmed ComicVine issue mapping, if any.
        embedded_cbl_issue_id: Exact ComicVine issue ID embedded in CBL evidence, if valid.

    Returns:
        A deterministic confirmed/candidate/unresolved decision.
    """
    usable = tuple(
        sorted(
            (score for score in scores if score.rejection_reason is None),
            key=lambda item: (-item.score, item.candidate.issue_id),
        )
    )

    if embedded_cbl_issue_id is not None:
        winner = next(
            (score for score in usable if score.candidate.issue_id == embedded_cbl_issue_id),
            None,
        )
        if winner is not None:
            return RepairDecision(
                status="confirmed",
                winner=winner,
                candidates=usable,
                reason="exact embedded CBL ComicVine issue ID validated against candidate evidence",
            )

    if existing_confirmed_issue_id is not None:
        winner = next(
            (score for score in usable if score.candidate.issue_id == existing_confirmed_issue_id),
            None,
        )
        return RepairDecision(
            status="confirmed",
            winner=winner,
            candidates=usable,
            reason="preserved existing confirmed ComicVine issue mapping",
        )

    if not usable:
        if any(score.stale_snapshot for score in scores):
            reason = "no validated local candidate; snapshot may be stale, so live refresh is required"
        else:
            reason = "no validated ComicVine candidate"
        return RepairDecision(status="unresolved", winner=None, candidates=(), reason=reason)

    best = usable[0]
    runner_up = usable[1] if len(usable) > 1 else None
    margin = best.score - runner_up.score if runner_up is not None else best.score
    if best.score >= AUTO_CONFIRM_THRESHOLD and margin >= AUTO_CONFIRM_MARGIN:
        return RepairDecision(
            status="confirmed",
            winner=best,
            candidates=usable,
            reason="top locally validated candidate is strong and unambiguous",
        )

    return RepairDecision(
        status="candidate",
        winner=None,
        candidates=usable,
        reason="multiple or insufficiently strong candidates require explicit review",
    )
