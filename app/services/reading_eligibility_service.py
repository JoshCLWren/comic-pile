"""Request-local Option E eligibility, filtered before queue or dice weighting."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reading_shadow_repository import load_shadow_inputs
from app.services.reading_list_cycle_validator import validate_reading_constraints
from app.services.reading_list_evaluator import ReadingSnapshot, ThreadEligibility, evaluate


@dataclass(frozen=True, slots=True)
class ReadingEligibilitySnapshot:
    """One validated reader result shared by all candidate-selection consumers."""

    user_id: int
    threads: Mapping[int, ThreadEligibility]
    queued_thread_ids: frozenset[int]

    def __post_init__(self) -> None:
        """Detach mutable inputs so consumers cannot change another caller's result."""
        object.__setattr__(self, "threads", MappingProxyType(dict(self.threads)))
        object.__setattr__(self, "queued_thread_ids", frozenset(self.queued_thread_ids))

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
    return ReadingEligibilitySnapshot(snapshot.user_id, evaluate(snapshot), queued_thread_ids)


async def load_eligibility_snapshot(
    db: AsyncSession, user_id: int
) -> ReadingEligibilitySnapshot:
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
    return build_eligibility_snapshot(
        snapshot,
        queued_thread_ids=frozenset(row.thread_id for row in inputs.stored if row.queue_position > 0),
    )
