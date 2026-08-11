"""Derive deterministic crossover templates from CBL and ComicVine evidence."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TemplateEvidence:
    """External evidence for one candidate crossover member."""

    issue_id: int
    cbl_positions: tuple[int, ...]
    cbl_source_paths: tuple[str, ...]
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


@dataclass(frozen=True, slots=True)
class DerivedCrossoverTemplate:
    """Rebuildable crossover suggestion that never creates continuity rules."""

    items: tuple[CrossoverTemplateItem, ...]
    conflicts: tuple[CrossoverTemplateConflict, ...]


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
        _median_position(item.cbl_positions)
        for item in ordered
        if _is_core(item) and item.cbl_positions
    ]
    first_core = min(core_positions) if core_positions else None
    last_core = max(core_positions) if core_positions else None

    items = tuple(
        CrossoverTemplateItem(
            issue_id=item.issue_id,
            suggested_position=index,
            role=_role(item, first_core=first_core, last_core=last_core),
            confidence="high" if _is_core(item) else "medium" if item.cbl_positions else "low",
            explanation=_explanation(item, first_core=first_core, last_core=last_core),
            source_paths=tuple(sorted(set(item.cbl_source_paths))),
        )
        for index, item in enumerate(ordered, start=1)
    )
    return DerivedCrossoverTemplate(items=items, conflicts=_order_conflicts(evidence))


def _is_core(item: TemplateEvidence) -> bool:
    return bool(
        item.target_story_arc_id
        and item.target_story_arc_id in item.story_arc_ids
    )


def _role(
    item: TemplateEvidence,
    *,
    first_core: float | None,
    last_core: float | None,
) -> str:
    if _is_core(item):
        return "core"
    position = _median_position(item.cbl_positions) if item.cbl_positions else None
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
    position = _median_position(item.cbl_positions)
    return (position if position is not None else float("inf"), item.issue_id)


def _median_position(positions: tuple[int, ...]) -> float | None:
    if not positions:
        return None
    values = sorted(positions)
    midpoint = len(values) // 2
    if len(values) % 2:
        return float(values[midpoint])
    return (values[midpoint - 1] + values[midpoint]) / 2


def _order_conflicts(
    evidence: tuple[TemplateEvidence, ...],
) -> tuple[CrossoverTemplateConflict, ...]:
    conflicts: list[CrossoverTemplateConflict] = []
    for index, first in enumerate(evidence):
        for second in evidence[index + 1 :]:
            comparisons = {
                (left > right) - (left < right)
                for left, right in zip(first.cbl_positions, second.cbl_positions, strict=False)
                if left != right
            }
            if len(comparisons) > 1:
                first_id, second_id = sorted((first.issue_id, second.issue_id))
                conflicts.append(CrossoverTemplateConflict(first_id, second_id))
    return tuple(sorted(set(conflicts), key=lambda item: (item.first_issue_id, item.second_issue_id)))
