"""Request-local Option E eligibility, filtered before queue or dice weighting."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_reading_execution_settings
from app.models import Dependency, Issue, Thread
from app.models.collection_exclusion import CollectionExclusion
from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList
from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.schemas.thread import ThreadResponse
from app.schemas.dependency import BlockingDependency, BlockingExplanation
from app.services.reading_list_cycle_validator import validate_reading_constraints
from app.services.reading_list_evaluator import (
    Blocker,
    ReadingSnapshot,
    ThreadEligibility,
    evaluate,
)


@dataclass(frozen=True, slots=True)
class ReadingEligibilitySnapshot:
    """One validated reader result shared by all candidate-selection consumers."""

    user_id: int
    threads: Mapping[int, ThreadEligibility]
    queued_thread_ids: frozenset[int]
    excluded_issue_ids: frozenset[int] = frozenset()
    unread_counts: Mapping[int, int] = field(default_factory=dict)
    issue_numbers: Mapping[int, str] = field(default_factory=dict)
    issue_labels: Mapping[int, str] = field(default_factory=dict)
    issue_thread_ids: Mapping[int, int] = field(default_factory=dict)
    list_labels: Mapping[int, str] = field(default_factory=dict)
    thread_labels: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Detach mutable inputs so consumers cannot change another caller's result."""
        object.__setattr__(self, "threads", MappingProxyType(dict(self.threads)))
        object.__setattr__(self, "queued_thread_ids", frozenset(self.queued_thread_ids))
        object.__setattr__(self, "excluded_issue_ids", frozenset(self.excluded_issue_ids))
        object.__setattr__(self, "unread_counts", MappingProxyType(dict(self.unread_counts)))
        object.__setattr__(self, "issue_numbers", MappingProxyType(dict(self.issue_numbers)))
        object.__setattr__(self, "issue_labels", MappingProxyType(dict(self.issue_labels)))
        object.__setattr__(self, "issue_thread_ids", MappingProxyType(dict(self.issue_thread_ids)))
        object.__setattr__(self, "list_labels", MappingProxyType(dict(self.list_labels)))
        object.__setattr__(self, "thread_labels", MappingProxyType(dict(self.thread_labels)))

    def candidate_ids(
        self,
        *,
        allowed_thread_ids: frozenset[int] | None = None,
        excluded_thread_ids: frozenset[int] = frozenset(),
    ) -> frozenset[int]:
        """Apply queue membership and caller filters without changing eligibility.

        Args:
            allowed_thread_ids: Optional format/session candidate restriction.
            excluded_thread_ids: Session skips, snoozes or other request exclusions.

        Returns:
            Eligible queued Thread IDs before weighting, preserving an empty filter.
        """
        return frozenset(
            thread_id
            for thread_id, result in self.threads.items()
            if result.eligible
            and thread_id in self.queued_thread_ids
            and thread_id not in excluded_thread_ids
            and (allowed_thread_ids is None or thread_id in allowed_thread_ids)
        )


def build_eligibility_snapshot(
    snapshot: ReadingSnapshot, *, queued_thread_ids: frozenset[int]
) -> ReadingEligibilitySnapshot:
    """Validate the complete graph before exposing any candidate IDs.

    Args:
        snapshot: Complete owner-scoped inputs, including inactive prerequisite sources.
        queued_thread_ids: Threads with a positive queue position in the same read.

    Returns:
        Immutable eligibility with concrete frontier IDs and blocker provenance.
    """
    validate_reading_constraints(snapshot)
    return ReadingEligibilitySnapshot(
        snapshot.user_id,
        evaluate(snapshot),
        queued_thread_ids,
        snapshot.excluded_issue_ids,
        Counter(
            issue.thread_id
            for issue in snapshot.issues
            if issue.status != "read" and issue.issue_id not in snapshot.excluded_issue_ids
        ),
        issue_thread_ids={issue.issue_id: issue.thread_id for issue in snapshot.issues},
    )


async def load_eligibility_snapshot(db: AsyncSession, user_id: int) -> ReadingEligibilitySnapshot:
    """Load once per request and pass the returned object to every consumer.

    Incomplete references fail closed. No stored frontier or cached blocked flag
    participates in evaluation. This loader does not activate Option E execution.

    Args:
        db: Current reader transaction.
        user_id: Owner whose candidate pool is being evaluated.

    Returns:
        Validated detached eligibility for this request.
    """
    inputs = await load_shadow_inputs(db, user_id)
    if inputs.unresolved:
        raise ValueError("Reading eligibility contains unresolved references")
    snapshot = ReadingSnapshot(
        user_id=inputs.user_id,
        threads=inputs.threads,
        issues=inputs.issues,
        lists=inputs.lists,
        prerequisites=inputs.prerequisites,
        excluded_issue_ids=inputs.excluded_issue_ids,
    )
    result = build_eligibility_snapshot(
        snapshot,
        queued_thread_ids=frozenset(
            row.thread_id for row in inputs.stored if row.queue_position > 0
        ),
    )
    return replace(
        result,
        issue_numbers=dict(inputs.issue_numbers),
        issue_labels=dict(inputs.issue_labels),
        list_labels=dict(inputs.list_labels),
        thread_labels=dict(inputs.thread_labels),
    )


async def get_execution_eligibility(
    db: AsyncSession, user_id: int
) -> ReadingEligibilitySnapshot | None:
    """Share one live answer within a request transaction when explicitly activated.

    Args:
        db: Request-owned async session; never a process-global cache.
        user_id: Authenticated reader.

    Returns:
        None for legacy execution, otherwise the transaction's immutable result.
    """
    settings = get_reading_execution_settings()
    if not settings.enabled:
        return None
    key = f"option_e_eligibility:{user_id}"
    # Match ordinary SELECT autoflush before evaluating pending reader writes.
    await db.flush()
    transaction = db.get_transaction()
    cached = db.info.get(key)
    if (
        isinstance(cached, tuple)
        and len(cached) == 2
        and cached[0] is transaction
        and isinstance(cached[1], ReadingEligibilitySnapshot)
    ):
        return cached[1]
    result = await load_eligibility_snapshot(db, user_id)
    db.info[key] = (db.get_transaction(), result)
    listener_key = "option_e_eligibility_flush_listener"
    if not db.info.get(listener_key):

        def invalidate_after_flush(session: object, context: object) -> None:
            """Discard snapshots after ORM writes, without changing reader data."""
            inputs = (
                Thread,
                Issue,
                Dependency,
                CollectionExclusion,
                CustomCBLList,
                CustomCBLEntry,
                CatalogIssue,
                CatalogSeries,
                ExternalIdentity,
                ThreadExternalSeriesMapping,
            )
            if not any(isinstance(row, inputs) for row in db.new | db.dirty | db.deleted):
                return
            for cache_key in tuple(db.info):
                if cache_key.startswith("option_e_eligibility:"):
                    db.info.pop(cache_key, None)

        event.listen(db.sync_session, "after_flush", invalidate_after_flush)
        db.info[listener_key] = True
    return result


def describe_blocker_origin(snapshot: ReadingEligibilitySnapshot, blocker: Blocker) -> str:
    """Name the actual list or prerequisite authority without exposing storage IDs.

    Args:
        snapshot: Shared reader context with owned list labels.
        blocker: One evaluator result with stable provenance.

    Returns:
        Reader-facing origin for Queue summaries and Roll recovery.
    """
    if blocker.kind == "prerequisite":
        return "Reader prerequisite" if blocker.origin == "reader" else "Converted prerequisite"
    kind = {
        "strict_order": "Strict order",
        "hold": "Hold",
        "after_previous": "Wait for previous",
    }[blocker.kind]
    return f"{kind} in {snapshot.list_labels.get(blocker.list_id, 'Reading List')}"


def project_blocking_explanation(
    snapshot: ReadingEligibilitySnapshot, thread_id: int,
) -> BlockingExplanation:
    """Project every live blocker with reader names and exact Issue links.

    Args:
        snapshot: The same validated result used by Roll and Queue.
        thread_id: Owned Thread to explain.

    Returns:
        All restrictions without consulting cached flags or legacy edges.
    """
    state = snapshot.threads.get(thread_id)
    dependencies: list[BlockingDependency] = []
    reasons: list[str] = []
    if state is not None:
        for blocker in state.blockers:
            origin = describe_blocker_origin(snapshot, blocker)
            for issue_id in blocker.waiting_on_issue_ids:
                source_thread_id = snapshot.issue_thread_ids[issue_id]
                label = f"{origin}: waiting on {snapshot.issue_labels.get(issue_id, 'required issue')}"
                reasons.append(label)
                dependencies.append(BlockingDependency(
                    issue_id=issue_id,
                    thread_id=source_thread_id,
                    thread_title=snapshot.thread_labels.get(source_thread_id, "Required series"),
                    issue_number=snapshot.issue_numbers.get(issue_id, ""),
                    label=label,
                ))
    if state is not None and state.next_issue_id is None:
        reasons.append("No available unread issue")
    return BlockingExplanation(
        is_blocked=bool(state is not None and not state.eligible),
        blocking_reasons=reasons,
        blocking_dependencies=dependencies,
    )


def project_thread_responses(
    responses: list[ThreadResponse], eligibility: ReadingEligibilitySnapshot | None
) -> list[ThreadResponse]:
    """Keep Queue and stale-offer metadata aligned without mutating ORM caches.

    Args:
        responses: Existing owner-scoped response DTOs.
        eligibility: Shared live authority, or None for unchanged legacy DTOs.

    Returns:
        Responses with the same frontier, count and availability used for selection.
    """
    if eligibility is None:
        return responses
    available = eligibility.candidate_ids()
    result: list[ThreadResponse] = []
    for response in responses:
        state = eligibility.threads.get(response.id)
        frontier = state.next_issue_id if state is not None else None
        reasons = project_blocking_explanation(eligibility, response.id).blocking_reasons
        blocked = response.status == "active" and response.id not in available
        if blocked and not reasons:
            reasons = [
                "No available unread issue"
                if frontier is None
                else "Series is outside the active queue"
            ]
        result.append(
            response.model_copy(
                update={
                    "is_blocked": blocked,
                    "blocking_reasons": reasons,
                    "next_unread_issue_id": frontier,
                    "next_unread_issue_number": eligibility.issue_numbers.get(frontier),
                    "issues_remaining": eligibility.unread_counts.get(response.id, 0),
                }
            )
        )
    return result
