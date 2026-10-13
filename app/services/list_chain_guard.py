"""Guards that keep retired generated list-chain edges from coming back.

Canonical policy: ``docs/roll-eligibility-contract.md`` (Josh, 2026-10-12).

A *retired list-chain edge* is a hard ``Dependency`` that merely duplicates
natural series order — source and target Issues sit on the same ``Thread`` and
the target is the source's immediate successor by ``Issue.position``. That
ordering is already enforced by ``Thread.next_unread_issue_id``; it must never
be an authoritative Roll blocker (contract "Not allowed": adding blockers for
same-series order, treating consecutive list entries as blockers).

Three legacy paths could reintroduce such edges and are guarded here:

1. Held production-migration scripts select ``extra_item_read_pairs`` for
   ``replace_compiled_rules``. Same-thread pairs are dropped before compile;
   caller-injected adjacency can never recreate a chain.
2. The canonical backfill migration (``canonical_backfill``) aborts via
   ``abort_on_retired_list_chain_rules`` when a rule-native ``item_read``
   ``ContinuityRule`` is a retired list-chain rule, so re-running the legacy
   migration cannot silently resurrect generated adjacency.
3. Stale ``nodes_json`` convergence flags are filtered in the plan writer so a
   convergence gate that only duplicates the node's own natural series
   predecessor compiles no edge.

Nothing here drops a genuine cross-thread checkpoint, a recorded standalone
prerequisite, or a convergence gate with real multi-source prerequisites.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from app.services.strict_plan_constraints import IssueThreadIndex


def is_retired_list_chain_pair(
    source_meta: IssueThreadIndex,
    target_meta: IssueThreadIndex,
) -> bool:
    """Return whether a pair only duplicates natural in-series order.

    Retired means same ``Thread`` and the target immediately follows the
    source by ``Issue.position`` — exactly what ``Issue.position`` and
    ``Thread.next_unread_issue_id`` already sequence, so the hard edge is
    prohibited by the Roll eligibility contract.

    Args:
        source_meta: Thread/position metadata for the source Issue.
        target_meta: Thread/position metadata for the target Issue.

    Returns:
        True when the pair is generated series-order adjacency.
    """
    return (
        source_meta.thread_id == target_meta.thread_id
        and target_meta.position == source_meta.position + 1
    )


def partition_retired_list_chain_pairs(
    pairs: Sequence[tuple[int, int]],
    index: Mapping[int, IssueThreadIndex],
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Split pairs into (allowed, retired) using Thread/position metadata.

    Pairs with unknown endpoint metadata are retired rather than guessed: an
    unverifiable restriction must not silently become authoritative.

    Args:
        pairs: Candidate ``(source_issue_id, target_issue_id)`` pairs.
        index: Issue metadata from ``load_issue_thread_index``.

    Returns:
        ``(kept, retired)`` preserving input order within each list.
    """
    kept: list[tuple[int, int]] = []
    retired: list[tuple[int, int]] = []
    for source_id, target_id in pairs:
        source_meta = index.get(source_id)
        target_meta = index.get(target_id)
        if source_meta is None or target_meta is None:
            retired.append((source_id, target_id))
            continue
        if is_retired_list_chain_pair(source_meta, target_meta):
            retired.append((source_id, target_id))
        else:
            kept.append((source_id, target_id))
    return kept, retired


def assert_no_same_thread_pairs(
    pairs: Collection[tuple[int, int]],
    index: Mapping[int, IssueThreadIndex],
) -> None:
    """Assert a migration pair selection contains no same-thread edges.

    Held production-migration scripts call this after selecting
    ``extra_item_read_pairs`` so a classification regression fails loudly
    instead of re-authoring whole-list chain edges.

    Args:
        pairs: Selected ``(source_issue_id, target_issue_id)`` pairs.
        index: Issue metadata from ``load_issue_thread_index``.

    Raises:
        ValueError: Listing each same-thread pair that may not compile.
    """
    offenders = [
        pair
        for pair in pairs
        if (
            (source_meta := index.get(pair[0])) is not None
            and (target_meta := index.get(pair[1])) is not None
            and source_meta.thread_id == target_meta.thread_id
        )
    ]
    if offenders:
        raise ValueError(
            "Migration selected same-thread item_read pair(s) "
            f"{sorted(offenders)}; same-series order is Issue.position "
            "geometry, not a hard Dependency (docs/roll-eligibility-contract.md)"
        )
