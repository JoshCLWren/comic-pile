"""Explain provenance-aware relationships between mapped ComicPile issues."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue


@dataclass(frozen=True, slots=True)
class CBLRelationshipObservation:
    """One source-list observation connecting two ComicPile issues."""

    repository: str
    source_path: str
    revision_sha: str
    first_position: int
    second_position: int

    @property
    def adjacent(self) -> bool:
        """Return whether the two entries are adjacent in this source list."""
        return abs(self.first_position - self.second_position) == 1


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    """Derived, non-blocking evidence connecting two ComicPile issues."""

    first_issue_id: int
    second_issue_id: int
    cbl_observations: tuple[CBLRelationshipObservation, ...]
    shared_story_arc_ids: tuple[str, ...]
    same_thread: bool
    serial_order: str | None

    @property
    def cooccurrence_count(self) -> int:
        """Return the number of current CBL lists containing both issues."""
        return len(self.cbl_observations)

    @property
    def distinct_source_count(self) -> int:
        """Return the number of distinct source repositories connecting the issues."""
        return len({item.repository for item in self.cbl_observations})

    @property
    def ordered_before_count(self) -> int:
        """Return how many CBL lists place the first issue before the second."""
        return sum(
            item.first_position < item.second_position for item in self.cbl_observations
        )

    @property
    def ordered_after_count(self) -> int:
        """Return how many CBL lists place the first issue after the second."""
        return sum(
            item.first_position > item.second_position for item in self.cbl_observations
        )

    @property
    def adjacent_count(self) -> int:
        """Return how many CBL lists place the two issues directly adjacent."""
        return sum(item.adjacent for item in self.cbl_observations)

    @property
    def explicit_story_arc_count(self) -> int:
        """Return the number of ComicVine story arcs shared by both issues."""
        return len(self.shared_story_arc_ids)

    @property
    def has_order_conflict(self) -> bool:
        """Return whether source lists disagree on relative order."""
        return self.ordered_before_count > 0 and self.ordered_after_count > 0


async def get_relationship_evidence(
    db: AsyncSession,
    *,
    first_issue_id: int,
    second_issue_id: int,
) -> RelationshipEvidence:
    """Derive inspectable external evidence connecting two ComicPile issues.

    This service deliberately does not create or modify continuity rules. CBL
    ordering remains an observation, ComicVine story-arc membership remains a
    separate evidence type, and same-thread serial context is reported without
    manufacturing a redundant dependency edge.

    Args:
        db: Async database session.
        first_issue_id: First ComicPile issue identifier.
        second_issue_id: Second ComicPile issue identifier.

    Returns:
        Deterministic relationship evidence derived from current imported data.

    Raises:
        ValueError: If the issues are identical, missing, or do not both have a
            confirmed ComicVine issue mapping.
    """
    if first_issue_id == second_issue_id:
        raise ValueError("relationship evidence requires two distinct issues")

    issues = list(
        (
            await db.execute(
                select(Issue).where(Issue.id.in_((first_issue_id, second_issue_id)))
            )
        )
        .scalars()
        .all()
    )
    by_id = {issue.id: issue for issue in issues}
    if first_issue_id not in by_id or second_issue_id not in by_id:
        raise ValueError("both ComicPile issues must exist")

    identity_rows = list(
        (
            await db.execute(
                select(IssueExternalIdentityMapping, ExternalIdentity)
                .join(
                    ExternalIdentity,
                    ExternalIdentity.id
                    == IssueExternalIdentityMapping.external_identity_id,
                )
                .where(
                    IssueExternalIdentityMapping.issue_id.in_(
                        (first_issue_id, second_issue_id)
                    ),
                    IssueExternalIdentityMapping.status == "confirmed",
                    ExternalIdentity.provider == "comicvine",
                    ExternalIdentity.entity_type == "issue",
                )
            )
        ).all()
    )
    identities: dict[int, ExternalIdentity] = {}
    for mapping, identity in identity_rows:
        identities[mapping.issue_id] = identity
    if first_issue_id not in identities or second_issue_id not in identities:
        raise ValueError("both issues require confirmed ComicVine issue mappings")

    first_identity = identities[first_issue_id]
    second_identity = identities[second_issue_id]
    cbl_rows = list(
        (
            await db.execute(
                select(CBLSourceEntry, CBLSourceList, CBLSource)
                .join(CBLSourceList, CBLSourceList.id == CBLSourceEntry.list_id)
                .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
                .where(
                    CBLSourceList.active.is_(True),
                    CBLSourceEntry.external_issue_identity_id.in_(
                        (first_identity.id, second_identity.id)
                    ),
                )
                .order_by(
                    CBLSource.repository,
                    CBLSourceList.source_path,
                    CBLSourceEntry.position,
                )
            )
        ).all()
    )

    entries_by_list: dict[int, dict[int, int]] = {}
    provenance_by_list: dict[int, tuple[str, str, str]] = {}
    identity_to_issue = {
        first_identity.id: first_issue_id,
        second_identity.id: second_issue_id,
    }
    for entry, source_list, source in cbl_rows:
        if entry.external_issue_identity_id is None:
            continue
        issue_id = identity_to_issue.get(entry.external_issue_identity_id)
        if issue_id is None:
            continue
        entries_by_list.setdefault(source_list.id, {})[issue_id] = entry.position
        provenance_by_list[source_list.id] = (
            source.repository,
            source_list.source_path,
            source_list.revision_sha,
        )

    observations: list[CBLRelationshipObservation] = []
    for list_id, positions in entries_by_list.items():
        if first_issue_id not in positions or second_issue_id not in positions:
            continue
        repository, source_path, revision_sha = provenance_by_list[list_id]
        observations.append(
            CBLRelationshipObservation(
                repository=repository,
                source_path=source_path,
                revision_sha=revision_sha,
                first_position=positions[first_issue_id],
                second_position=positions[second_issue_id],
            )
        )

    first_arcs = _story_arc_ids(first_identity.metadata_json)
    second_arcs = _story_arc_ids(second_identity.metadata_json)
    shared_story_arc_ids = tuple(sorted(first_arcs & second_arcs))

    first_issue = by_id[first_issue_id]
    second_issue = by_id[second_issue_id]
    same_thread = first_issue.thread_id == second_issue.thread_id
    serial_order: str | None = None
    if same_thread:
        if first_issue.position < second_issue.position:
            serial_order = "before"
        elif first_issue.position > second_issue.position:
            serial_order = "after"

    return RelationshipEvidence(
        first_issue_id=first_issue_id,
        second_issue_id=second_issue_id,
        cbl_observations=tuple(observations),
        shared_story_arc_ids=shared_story_arc_ids,
        same_thread=same_thread,
        serial_order=serial_order,
    )


def _story_arc_ids(metadata: dict[str, object]) -> set[str]:
    """Extract normalized story-arc IDs from hydrated ComicVine metadata."""
    raw_arcs = metadata.get("story_arcs")
    if not isinstance(raw_arcs, list):
        return set()

    result: set[str] = set()
    for item in raw_arcs:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if isinstance(raw_id, int):
            result.add(str(raw_id))
        elif isinstance(raw_id, str) and raw_id.strip():
            result.add(raw_id.strip())
    return result
