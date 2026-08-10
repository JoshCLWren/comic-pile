"""Persistence boundary for confidence-aware ComicVine identity repair."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
    upsert_external_identity,
)
from app.models.external_identity import IssueExternalIdentityMapping
from comic_pile.comicvine_identity_repair import CandidateScore, RepairDecision


def _candidate_evidence(score: CandidateScore, decision_reason: str) -> dict[str, object]:
    """Serialize explainable scoring evidence without losing segment/freshness details."""
    candidate = score.candidate
    return {
        "score": score.score,
        "evidence": list(score.evidence),
        "stale_snapshot": score.stale_snapshot,
        "decision_reason": decision_reason,
        "rejection_reason": score.rejection_reason,
        "volume_id": candidate.volume_id,
        "volume_name": candidate.volume_name,
        "publisher": candidate.publisher,
        "start_year": candidate.start_year,
        "issue_number": candidate.issue_number,
        "issue_name": candidate.issue_name,
        "segment_start": candidate.segment_start,
        "segment_end": candidate.segment_end,
    }


async def persist_repair_decision(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    decision: RepairDecision,
) -> list[IssueExternalIdentityMapping]:
    """Persist all scored candidates while confirming only the decision winner."""
    persisted: list[IssueExternalIdentityMapping] = []
    winner_id = decision.winner.candidate.issue_id if decision.winner is not None else None

    for score in (*decision.candidates, *decision.rejected):
        candidate = score.candidate
        identity = await upsert_external_identity(
            db,
            provider="comicvine",
            entity_type="issue",
            external_id=str(candidate.issue_id),
            metadata_json={
                "issue_number": candidate.issue_number,
                "name": candidate.issue_name,
                "volume": {"id": candidate.volume_id, "name": candidate.volume_name},
            },
        )
        if score.rejection_reason is not None:
            status = "rejected"
            rejection_reason = score.rejection_reason
        elif decision.status == "confirmed" and candidate.issue_id == winner_id:
            status = "confirmed"
            rejection_reason = None
        else:
            status = "candidate"
            rejection_reason = None
        mapping = await link_issue_external_identity(
            db,
            user_id=user_id,
            issue_id=issue_id,
            external_identity_id=identity.id,
            status=status,
            evidence_source=candidate.source,
            confidence=score.score,
            rejection_reason=rejection_reason,
        )
        mapping.evidence_json = _candidate_evidence(score, decision.reason)
        persisted.append(mapping)

    return persisted


async def review_candidate_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    issue_id: int,
    external_identity_id: int,
    status: str,
    rejection_reason: str | None = None,
) -> IssueExternalIdentityMapping:
    """Manually confirm or reject one persisted candidate without discarding its audit evidence."""
    if status not in {"confirmed", "rejected"}:
        raise ExternalIdentityMappingError("manual candidate review must confirm or reject")
    if status == "rejected" and not (rejection_reason or "").strip():
        raise ExternalIdentityMappingError("rejection_reason is required when rejecting a candidate")

    existing = await db.scalar(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue_id,
            IssueExternalIdentityMapping.external_identity_id == external_identity_id,
        )
    )
    if existing is None:
        raise ExternalIdentityMappingError("candidate mapping does not exist")

    evidence_json = dict(existing.evidence_json)
    mapping = await link_issue_external_identity(
        db,
        user_id=user_id,
        issue_id=issue_id,
        external_identity_id=external_identity_id,
        status=status,
        evidence_source=existing.evidence_source,
        confidence=existing.confidence,
        rejection_reason=rejection_reason if status == "rejected" else None,
    )
    mapping.evidence_json = evidence_json
    return mapping
