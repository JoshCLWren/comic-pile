"""Canonical issue deduplication for reader-facing blocker projections."""

from collections.abc import Iterable
from dataclasses import replace

from app.services.reading_list_evaluator import Blocker


def unique_blocker_requirements(blockers: Iterable[Blocker]) -> tuple[Blocker, ...]:
    """Describe each required Issue once, retaining the first governing origin.

    Args:
        blockers: Evaluator blockers in their stable presentation order.

    Returns:
        Presentation copies containing only previously undescribed requirements.
        The evaluator blockers and their eligibility semantics remain unchanged.
    """
    seen: set[int] = set()
    projected: list[Blocker] = []
    for blocker in blockers:
        remaining = tuple(i for i in blocker.waiting_on_issue_ids if i not in seen)
        if not blocker.waiting_on_issue_ids:
            projected.append(blocker)
        elif remaining:
            projected.append(replace(blocker, waiting_on_issue_ids=remaining))
            seen.update(remaining)
    return tuple(projected)
