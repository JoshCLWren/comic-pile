"""Derive deterministic crossover templates from CBL and ComicVine evidence."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping


@dataclass(frozen=True, slots=True, order=True)
class CBLPlacement:
    """One ordered CBL observation with inseparable provenance."""

    source_path: str
    position: int


@dataclass(frozen=True, slots=True)
class TemplateEvidence:
    """External evidence for one candidate crossover member."""

    issue_id: int
    cbl_placements: tuple[CBLPlacement, ...]
    story_arc_ids: tuple[str, ...] = ()
    target_story_arc_id: str | None = None


@dataclass(frozen=True, slots=True)
class CrossoverTemplateItem:
    """One suggested, non-blocking member of a derived crossover template."""

    issue_id: int
    suggested_position: int
    role: str
    confidence: str
    explanation: str
    source_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CrossoverTemplateConflict:
    """A pair whose relative order disagrees across source lists."""

    first_issue_id: int
    second_issue_id: int
    source_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DerivedCrossoverTemplate:
    """Rebuildable crossover suggestion that never creates continuity rules."""

    items: tuple[CrossoverTemplateItem, ...]
    conflicts: tuple[CrossoverTemplateConflict, ...]


async def derive_crossover_template_from_lists(
    db: AsyncSession,
    *,
    source_list_ids: tuple[int, ...],
    target_story_arc_id: str,
) -> DerivedCrossoverTemplate:
    """Build a crossover template from persisted CBL and ComicVine evidence.

    Only confirmed ComicVine issue mappings are eligible for ComicPile template
    members. CBL ordering remains advisory evidence. This function reads source
    state only and never creates or mutates continuity rules or user plans.

    Args:
        db: Async database session.
        source_list_ids: Active imported CBL lists to combine.
        target_story_arc_id: ComicVine story-arc identity defining explicit core membership.

    Returns:
        Deterministic derived template with inspectable provenance and conflicts.
    """
    if not source_list_ids:
        return DerivedCrossoverTemplate(items=(), conflicts=())

    rows = list(
        (
            await db.execute(
                select(
                    CBLSourceEntry,
                    CBLSourceList,
                    CBLSource,
                    IssueExternalIdentityMapping,
                    ExternalIdentity,
                )
                .join(CBLSourceList, CBLSourceList.id == CBLSourceEntry.list_id)
                .join(CBLSource, CBLSource.id == CBLSourceList.source_id)
                .join(
                    IssueExternalIdentityMapping,
                    IssueExternalIdentityMapping.external_identity_id
                    == CBLSourceEntry.external_issue_identity_id,
                )
                .join(
                    ExternalIdentity,
                    ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
                )
                .where(
                    CBLSourceEntry.list_id.in_(source_list_ids),
                    CBLSourceList.active.is_(True),
                    IssueExternalIdentityMapping.status == "confirmed",
                    ExternalIdentity.provider == "comicvine",
                    ExternalIdentity.entity_type == "issue",
                )
                .order_by(
                    CBLSource.repository,
                    CBLSourceList.source_path,
                    CBLSourceEntry.position,
                    IssueExternalIdentityMapping.issue_id,
                )
            )
        ).all()
    )

    placements_by_issue: dict[int, list[CBLPlacement]] = {}
    arcs_by_issue: dict[int, set[str]] = {}
    for entry, source_list, source, mapping, identity in rows:
        source_path = f"{source.repository}:{source_list.source_path}"
        placements_by_issue.setdefault(mapping.issue_id, []).append(
            CBLPlacement(source_path=source_path, position=entry.position)
        )
        arcs_by_issue.setdefault(mapping.issue_id, set()).update(
            _story_arc_ids(identity.metadata_json)
        )

    evidence = tuple(
        TemplateEvidence(
            issue_id=issue_id,
            cbl_placements=tuple(sorted(placements)),
            story_arc_ids=tuple(sorted(arcs_by_issue.get(issue_id, set()))),
            target_story_arc_id=target_story_arc_id,
        )
        for issue_id, placements in sorted(placements_by_issue.items())
    )
    return derive_crossover_template(evidence)


def derive_crossover_template(
    evidence: tuple[TemplateEvidence, ...],
) -> DerivedCrossoverTemplate:
    """Derive a stable template while preserving uncertainty and provenance.

    ComicVine membership is sufficient for a ``core`` role only when the caller
    supplies the target story-arc identity. CBL-only members remain contextual
    candidates when they surround known core members, otherwise ``unknown``.
    Source-order disagreements are reported rather than flattened into hard
    dependency semantics.
    """
    if not evidence:
        return DerivedCrossoverTemplate(items=(), conflicts=())

    ordered = tuple(sorted(evidence, key=_sort_key))
    core_positions = [
        position
        for item in ordered
        if _is_core(item)
        for position in [_median_position(item)]
        if position is not None
    ]
    first_core = min(core_positions) if core_positions else None
    last_core = max(core_positions) if core_positions else None

    items = tuple(
        CrossoverTemplateItem(
            issue_id=item.issue_id,
            suggested_position=index,
            role=_role(item, first_core=first_core, last_core=last_core),
            confidence="high" if _is_core(item) else "medium" if item.cbl_placements else "low",
            explanation=_explanation(item, first_core=first_core, last_core=last_core),
            source_paths=tuple(sorted({placement.source_path for placement in item.cbl_placements})),
        )
        for index, item in enumerate(ordered, start=1)
    )
    return DerivedCrossoverTemplate(items=items, conflicts=_order_conflicts(evidence))


def _is_core(item: TemplateEvidence) -> bool:
    return bool(item.target_story_arc_id and item.target_story_arc_id in item.story_arc_ids)


def _role(
    item: TemplateEvidence,
    *,
    first_core: float | None,
    last_core: float | None,
) -> str:
    if _is_core(item):
        return "core"
    position = _median_position(item)
    if position is None or first_core is None or last_core is None:
        return "unknown"
    if position < first_core:
        return "context/prelude"
    if position > last_core:
        return "epilogue"
    return "unknown"


def _explanation(
    item: TemplateEvidence,
    *,
    first_core: float | None,
    last_core: float | None,
) -> str:
    role = _role(item, first_core=first_core, last_core=last_core)
    if role == "core":
        return f"ComicVine explicitly tags this issue with story arc {item.target_story_arc_id}."
    if role == "context/prelude":
        return "CBL places this issue before the explicit ComicVine core; role remains contextual."
    if role == "epilogue":
        return "CBL places this issue after the explicit ComicVine core; role remains contextual."
    return "External evidence suggests membership but is insufficient to assign a core/context role."


def _sort_key(item: TemplateEvidence) -> tuple[float, int]:
    position = _median_position(item)
    return (position if position is not None else float("inf"), item.issue_id)


def _median_position(item: TemplateEvidence) -> float | None:
    positions = sorted(placement.position for placement in item.cbl_placements)
    if not positions:
        return None
    midpoint = len(positions) // 2
    if len(positions) % 2:
        return float(positions[midpoint])
    return (positions[midpoint - 1] + positions[midpoint]) / 2


def _order_conflicts(
    evidence: tuple[TemplateEvidence, ...],
) -> tuple[CrossoverTemplateConflict, ...]:
    conflicts: list[CrossoverTemplateConflict] = []
    for index, first in enumerate(evidence):
        first_by_path = {placement.source_path: placement.position for placement in first.cbl_placements}
        for second in evidence[index + 1 :]:
            second_by_path = {
                placement.source_path: placement.position for placement in second.cbl_placements
            }
            shared_paths = sorted(first_by_path.keys() & second_by_path.keys())
            comparisons = {
                (first_by_path[path] > second_by_path[path])
                - (first_by_path[path] < second_by_path[path])
                for path in shared_paths
                if first_by_path[path] != second_by_path[path]
            }
            if len(comparisons) > 1:
                first_id, second_id = sorted((first.issue_id, second.issue_id))
                conflicts.append(
                    CrossoverTemplateConflict(
                        first_issue_id=first_id,
                        second_issue_id=second_id,
                        source_paths=tuple(shared_paths),
                    )
                )
    return tuple(
        sorted(
            set(conflicts),
            key=lambda item: (item.first_issue_id, item.second_issue_id, item.source_paths),
        )
    )


def _story_arc_ids(metadata: dict[str, object]) -> set[str]:
    """Extract normalized ComicVine story-arc identifiers from provider metadata."""
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
