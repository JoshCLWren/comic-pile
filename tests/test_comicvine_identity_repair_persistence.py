"""Persistence tests for ComicVine identity repair decisions."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_identity_repair import persist_repair_decision, review_candidate_mapping
from app.external_identities import ExternalIdentityMappingError
from app.models import Issue, Thread, User
from comic_pile.comicvine_identity_repair import (
    ComicVineCandidate,
    ComicVineRepairContext,
    decide_candidates,
    score_candidate,
)


async def _owned_issue(db: AsyncSession, *, username: str) -> tuple[User, Issue]:
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title="X-Men",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="12", position=1)
    db.add(issue)
    await db.flush()
    return user, issue


@pytest.mark.asyncio
async def test_persist_repair_decision_records_score_evidence_and_segment(
    async_db: AsyncSession,
) -> None:
    """Persisted candidates should retain explainable score, segment, and source evidence."""
    user, issue = await _owned_issue(async_db, username="repair_persist")
    context = ComicVineRepairContext(
        title="X-Men",
        issue_label="12",
        publisher="Marvel",
        start_year=1991,
    )
    score = score_candidate(
        context,
        ComicVineCandidate(
            issue_id=1234,
            volume_id=5678,
            volume_name="X-Men",
            issue_number="12",
            publisher="Marvel",
            start_year=1991,
            segment_start="1",
            segment_end="41",
        ),
    )
    decision = decide_candidates([score])

    mappings = await persist_repair_decision(
        async_db,
        user_id=user.id,
        issue_id=issue.id,
        decision=decision,
    )

    assert len(mappings) == 1
    mapping = mappings[0]
    assert mapping.status == "confirmed"
    assert mapping.confidence == score.score
    assert mapping.evidence_source == "comicvine-local-sqlite"
    assert mapping.evidence_json["segment_start"] == "1"
    assert mapping.evidence_json["segment_end"] == "41"
    assert mapping.evidence_json["stale_snapshot"] is False
    evidence = mapping.evidence_json["evidence"]
    assert isinstance(evidence, list)
    assert "publisher matches" in evidence


@pytest.mark.asyncio
async def test_manual_review_preserves_evidence_and_requires_rejection_reason(
    async_db: AsyncSession,
) -> None:
    """Manual confirm/reject decisions should preserve candidate audit evidence."""
    user, issue = await _owned_issue(async_db, username="repair_review")
    context = ComicVineRepairContext(title="X-Men", issue_label="12")
    first = score_candidate(
        context,
        ComicVineCandidate(
            issue_id=11,
            volume_id=1,
            volume_name="X-Men",
            issue_number="12",
        ),
    )
    second = score_candidate(
        context,
        ComicVineCandidate(
            issue_id=22,
            volume_id=2,
            volume_name="X-Men",
            issue_number="12",
        ),
    )
    mappings = await persist_repair_decision(
        async_db,
        user_id=user.id,
        issue_id=issue.id,
        decision=decide_candidates([first, second]),
    )
    target = mappings[0]
    original_evidence = dict(target.evidence_json)

    with pytest.raises(ExternalIdentityMappingError, match="rejection_reason"):
        await review_candidate_mapping(
            async_db,
            user_id=user.id,
            issue_id=issue.id,
            external_identity_id=target.external_identity_id,
            status="rejected",
        )

    rejected = await review_candidate_mapping(
        async_db,
        user_id=user.id,
        issue_id=issue.id,
        external_identity_id=target.external_identity_id,
        status="rejected",
        rejection_reason="Wrong era despite matching title",
    )

    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "Wrong era despite matching title"
    assert rejected.evidence_json == original_evidence
