"""Adopt one provider-backed ComicVine issue into an existing owned thread.

This is the shared primitive for continuous release intake (#3114) and #2772:
given a target thread and a ComicVine issue from a confirmed/matched volume,
it idempotently creates or reuses the canonical ComicPile Issue and confirms
its ComicVine identity through the existing #2722 mapping semantics.

Guarantees:

- ComicVine issue numbers are preserved verbatim (never coerced to ranges).
- A confirmed ComicVine identity that already maps to an owned Issue is
  reused; retries never create a second Issue.
- Conflicting confirmed identities fail closed with a bounded ``conflict``
  result and never mutate the conflicting mapping.
- New issues are seated through the existing natural-order insertion path.
- Existing read state, ratings, history, dependencies, tags, and confirmed
  identities are preserved (only ``position`` may be reseated).
- Thread issue-tracking counters are recalculated through the existing
  derivation so a completed thread reopens when an unread issue arrives.
- Provider hydration goes through the existing ComicVine hydration boundary;
  a hydration failure after safe local creation is recoverable and a retry
  reuses the local state instead of duplicating it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.comicvine_hydration import hydrate_issue
from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
    upsert_external_identity,
)
from app.models import Event, Issue, Thread
from app.models.external_identity import ExternalIdentity
from app.repositories import issue_repository
from app.services.issue import _insert_new_issues_in_natural_order
from app.services.issue_tracking import apply_thread_issue_tracking_state
from app.services.ownership import get_owned_thread_or_404
from app.utils.issue_natural_order import natural_issue_order
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError
from comic_pile.dependencies import refresh_user_blocked_status

logger = logging.getLogger(__name__)

COMICVINE_PROVIDER = "comicvine"
ADOPTION_EVIDENCE_SOURCE = "comicvine_issue_adoption"
"""Canonical provenance for identities confirmed by provider issue adoption."""

AdoptionOutcome = Literal["created", "reused", "conflict"]
HydrationOutcome = Literal["hydrated", "failed", "not_attempted"]


@dataclass(frozen=True, slots=True)
class ProviderIssueAdoptionResult:
    """Typed result of adopting one provider issue into a thread.

    Attributes:
        outcome: ``created`` when a new Issue row was persisted, ``reused``
            when the confirmed ComicVine identity already mapped to (or the
            thread already contained) the canonical Issue, ``conflict`` when
            a conflicting confirmed identity blocked adoption.
        issue_id: The adopted canonical Issue ID, or None when adoption was
            blocked before a canonical Issue could be identified.
        thread_id: Target thread the issue was adopted into.
        comicvine_issue_id: ComicVine issue identity that was adopted.
        hydration: Provider-metadata hydration outcome for this call.
        conflict_detail: Bounded explanation when ``outcome`` is ``conflict``.
    """

    outcome: AdoptionOutcome
    issue_id: int | None
    thread_id: int
    comicvine_issue_id: int
    hydration: HydrationOutcome
    conflict_detail: str | None = None


async def _create_issue_in_natural_order(
    db: AsyncSession,
    thread_id: int,
    issue_number: str,
) -> Issue:
    """Create one unread issue through the existing natural-order path.

    When automatic placement is ambiguous (irregular numbering or a
    hand-reordered series), the issue is appended after the current last
    position, mirroring the append-only fallback of the issue creation path.

    Args:
        db: Database session.
        thread_id: Thread receiving the issue.
        issue_number: ComicVine issue number, stored verbatim.

    Returns:
        The newly created issue.
    """
    existing_rows = await issue_repository.locked_issue_rows(db, thread_id)
    existing_issue_numbers = [row[1] for row in existing_rows]
    natural_order = natural_issue_order(existing_issue_numbers, [issue_number])
    if natural_order is not None:
        created = await _insert_new_issues_in_natural_order(
            db, thread_id, [issue_number], natural_order
        )
        await db.flush()
        return created[0]

    next_position = max((row[2] for row in existing_rows), default=0) + 1
    issue = Issue(
        thread_id=thread_id,
        issue_number=issue_number,
        position=next_position,
        status="unread",
    )
    await issue_repository.add_issue(db, issue)
    await db.flush()
    return issue


async def _recalculate_thread_tracking(
    db: AsyncSession,
    thread: Thread,
    user_id: int,
) -> None:
    """Re-run the existing thread issue-tracking recalculation after adoption.

    Mirrors the lifecycle transitions of the issue creation path so a
    completed thread becomes active again when a new unread issue is added.

    Args:
        db: Database session.
        thread: Locked thread that received the issue.
        user_id: Owner of the thread (for queue reseating).
    """
    was_unmigrated = thread.total_issues is None
    had_next_unread_issue = thread.next_unread_issue_id is not None

    adopted_issues = await issue_repository.issues_ordered(db, thread.id)
    tracking_state = apply_thread_issue_tracking_state(thread, adopted_issues)

    if tracking_state.next_unread_issue_id is None:
        thread.status = "completed"
    elif was_unmigrated or not had_next_unread_issue:
        if not was_unmigrated and thread.status == "completed":
            await db.execute(
                update(Thread)
                .where(Thread.user_id == user_id)
                .where(Thread.status == "active")
                .values(queue_position=Thread.queue_position + 1)
            )
            thread.queue_position = 1
        thread.status = "active"

    db.add(Event(type="issues_created", timestamp=datetime.now(UTC), thread_id=thread.id))
    await refresh_user_blocked_status(user_id, db)


async def adopt_comicvine_issue(
    db: AsyncSession,
    *,
    user_id: int,
    thread_id: int,
    comicvine_issue_id: int,
    issue_number: str,
    external_url: str | None = None,
    metadata: dict[str, object] | None = None,
    comicvine_client: ComicVineClient | None = None,
) -> ProviderIssueAdoptionResult:
    """Adopt one ComicVine issue into an owned thread, idempotently.

    Args:
        db: Async database session; the caller owns the transaction commit.
        user_id: Owner of the target thread (authorization).
        thread_id: Target thread; must be owned by ``user_id``.
        comicvine_issue_id: Stable ComicVine issue ID from the confirmed volume.
        issue_number: ComicVine's issue number, preserved verbatim.
        external_url: Optional ComicVine site URL for the identity.
        metadata: Optional trusted provider facts stored on first identity
            creation; never overwrites richer hydrated metadata on retry.
        comicvine_client: Optional configured ComicVine client. When present,
            provider metadata is hydrated through the existing hydration
            boundary after the local state is safely established. A hydration
            failure is recorded on the result and never rolls back the local
            adoption, so a retry reuses the Issue instead of duplicating it.

    Returns:
        A :class:`ProviderIssueAdoptionResult` distinguishing ``created``,
        ``reused``, and ``conflict`` plus the hydration outcome.

    Raises:
        HTTPException: 404 when the thread does not exist or is not owned.
    """
    thread = await get_owned_thread_or_404(db, user_id, thread_id, for_update=True)
    external_id = str(comicvine_issue_id)

    existing = await issue_repository.find_owned_issue_by_confirmed_identity(
        db, user_id, provider=COMICVINE_PROVIDER, external_id=external_id
    )
    if existing is not None:
        if existing.thread_id != thread_id:
            return ProviderIssueAdoptionResult(
                outcome="conflict",
                issue_id=existing.id,
                thread_id=thread_id,
                comicvine_issue_id=comicvine_issue_id,
                hydration="not_attempted",
                conflict_detail=(
                    f"ComicVine issue {comicvine_issue_id} is already confirmed on "
                    f"issue {existing.id} of thread {existing.thread_id}"
                ),
            )
        issue = existing
        outcome: AdoptionOutcome = "reused"
    else:
        identity_exists = (
            await db.scalar(
                select(ExternalIdentity.id).where(
                    ExternalIdentity.provider == COMICVINE_PROVIDER,
                    ExternalIdentity.entity_type == "issue",
                    ExternalIdentity.external_id == external_id,
                )
            )
        ) is not None
        identity = await upsert_external_identity(
            db,
            provider=COMICVINE_PROVIDER,
            entity_type="issue",
            external_id=external_id,
            external_url=external_url,
            metadata_json=None if identity_exists else (metadata or {}),
        )

        issue = await issue_repository.find_in_thread_by_number(db, thread_id, issue_number)
        if issue is None:
            issue = await _create_issue_in_natural_order(db, thread_id, issue_number)
            outcome = "created"
        else:
            outcome = "reused"

        try:
            await link_issue_external_identity(
                db,
                user_id=user_id,
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source=ADOPTION_EVIDENCE_SOURCE,
                confidence=1.0,
            )
        except ExternalIdentityMappingError as exc:
            return ProviderIssueAdoptionResult(
                outcome="conflict",
                issue_id=issue.id,
                thread_id=thread_id,
                comicvine_issue_id=comicvine_issue_id,
                hydration="not_attempted",
                conflict_detail=str(exc),
            )

        if outcome == "created":
            await _recalculate_thread_tracking(db, thread, user_id)

    hydration: HydrationOutcome = "not_attempted"
    if comicvine_client is not None:
        try:
            await hydrate_issue(db, comicvine_client, comicvine_issue_id)
            hydration = "hydrated"
        except (ComicVineError, TimeoutError) as exc:
            hydration = "failed"
            logger.info(
                "comicvine_issue_adoption_hydration_failed thread_id=%s "
                "issue_id=%s comicvine_issue_id=%s error=%s",
                thread_id,
                issue.id,
                comicvine_issue_id,
                type(exc).__name__,
            )

    return ProviderIssueAdoptionResult(
        outcome=outcome,
        issue_id=issue.id,
        thread_id=thread_id,
        comicvine_issue_id=comicvine_issue_id,
        hydration=hydration,
    )
