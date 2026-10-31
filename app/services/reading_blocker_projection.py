"""Canonical Issue deduplication for reader-facing blocker projections.

The evaluator keeps one blocker per gate: a strict-order restriction, a hold
milestone, an ``after_previous`` gate, or an authored prerequisite. Several
gates can require the *same* unread Issue. Reader copy must describe that Issue
once, count it once, and still keep every governing gate visible so the reader
can edit each rule that blocks them.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from app.services.reading_list_evaluator import Blocker


@dataclass(frozen=True, slots=True)
class DescribedBlockerGate:
    """One evaluator gate plus the canonical Issues it is first to describe.

    Attributes:
        blocker: The original evaluator gate. It retains every required Issue so
            the gate's editor target stays resolvable even when another gate
            already described those Issues.
        described_issue_ids: Required Issues this gate is the first to describe,
            in the evaluator's stable order. Empty when every required Issue was
            already described by an earlier gate.
    """

    blocker: Blocker
    described_issue_ids: tuple[int, ...]


def describe_blocker_gates(blockers: Iterable[Blocker]) -> tuple[DescribedBlockerGate, ...]:
    """Keep every gate visible while naming each required Issue only once.

    Args:
        blockers: Evaluator blockers in their stable presentation order.

    Returns:
        One entry per evaluator gate in the same order. Eligibility semantics and
        the evaluator's own blocker tuples are untouched; only the reader
        description is deduplicated by canonical target Issue. A gate whose
        required Issues were all described earlier keeps an empty
        ``described_issue_ids`` so its rule and editor remain reachable.
    """
    described: set[int] = set()
    gates: list[DescribedBlockerGate] = []
    for blocker in blockers:
        new_ids = tuple(
            issue_id
            for issue_id in blocker.waiting_on_issue_ids
            if issue_id not in described
        )
        described.update(new_ids)
        gates.append(DescribedBlockerGate(blocker, new_ids))
    return tuple(gates)


def described_requirement_ids(gates: Iterable[DescribedBlockerGate]) -> tuple[int, ...]:
    """Return every canonical blocking Issue once, in stable gate order.

    Args:
        gates: Projected gates, whose described Issue sets are disjoint.

    Returns:
        Required Issue identifiers in the order a reader should meet them.
    """
    return tuple(
        issue_id for gate in gates for issue_id in gate.described_issue_ids
    )


def requirement_count(gates: Iterable[DescribedBlockerGate]) -> int:
    """Count canonical blocking Issues, not the gates that point at them.

    Args:
        gates: Projected gates, whose described Issue sets are disjoint.

    Returns:
        Number of distinct blocking Issues a reader must resolve.
    """
    return len(described_requirement_ids(gates))
