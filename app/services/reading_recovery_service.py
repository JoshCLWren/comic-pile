"""Bounded Roll recovery projected from the same live eligibility authority."""

from app.schemas.continuity_blocking import ContinuityBlocker, UnreadIssueDetail
from app.schemas.roll import (
    RollRecoveryChainNode,
    RollRecoveryDiagnostic,
    RollRecoveryInfo,
    RollRecoveryPrerequisite,
)
from app.services.reading_eligibility_service import (
    ReadingEligibilitySnapshot,
    describe_blocker_origin,
)


MAX_DEPTH = 32
MAX_NODES = 500


def build_reading_recovery(
    snapshot: ReadingEligibilitySnapshot,
    *,
    pending_thread_id: int,
    pending_thread_title: str | None,
    excluded_thread_ids: frozenset[int],
) -> RollRecoveryInfo | None:
    """Explain pending blockers without consulting retired continuity authorities.

    Args:
        snapshot: Validated request snapshot with owned labels and frontier identities.
        pending_thread_id: Preserved pending selection.
        pending_thread_title: Existing display title, when already available.
        excluded_thread_ids: Current session and durable snooze/skip exclusions.

    Returns:
        Concrete direct blockers and bounded paths to currently offerable frontiers.
    """
    pending = snapshot.threads.get(pending_thread_id)
    if pending is None or not pending.blockers:
        return None
    available = snapshot.candidate_ids(excluded_thread_ids=excluded_thread_ids)
    diagnostics: list[RollRecoveryDiagnostic] = []
    visited_count = 0

    def walk(issue_id: int, ancestors: frozenset[int]) -> list[list[RollRecoveryChainNode]]:
        """Follow issue constraints and natural-series frontiers with hard bounds."""
        nonlocal visited_count
        label = snapshot.issue_labels.get(issue_id, "Required issue")
        node = RollRecoveryChainNode(
            node_type="issue", node_id=issue_id, label=label, is_readable=False
        )
        if issue_id in ancestors or len(ancestors) >= MAX_DEPTH or visited_count >= MAX_NODES:
            if issue_id in ancestors:
                code = "cycle_detected"
                limit = None
            elif len(ancestors) >= MAX_DEPTH:
                code = "depth_limit_exceeded"
                limit = MAX_DEPTH
            else:
                code = "node_limit_exceeded"
                limit = MAX_NODES
            diagnostics.append(
                RollRecoveryDiagnostic(
                    code=code,
                    node_type="issue",
                    node_id=issue_id,
                    limit=limit,
                )
            )
            return [[node]]
        visited_count += 1
        thread_id = snapshot.issue_thread_ids[issue_id]
        state = snapshot.threads.get(thread_id)
        if state is None or state.next_issue_id is None:
            return [[node]]
        if state.next_issue_id != issue_id:
            waiting = [state.next_issue_id]
        elif state.blockers:
            waiting = sorted(
                {source for blocker in state.blockers for source in blocker.waiting_on_issue_ids}
            )
        else:
            node.is_readable = thread_id in available
            return [[node]]
        return [
            [node, *tail] for source in waiting for tail in walk(source, ancestors | {issue_id})
        ]

    direct: list[ContinuityBlocker] = []
    chains: list[list[RollRecoveryChainNode]] = []
    recommended: dict[int, RollRecoveryPrerequisite] = {}
    # One pending Issue is one recovery blocker even when several gates (for
    # example a hold milestone and strict order) require it. Merge every gate's
    # origin into that single note so no rule is hidden from the reader.
    origins_by_issue: dict[int, list[str]] = {}
    for blocker in pending.blockers:
        origin = describe_blocker_origin(snapshot, blocker)
        if blocker.provenance:
            origin += "; " + "; ".join(blocker.provenance)
        for issue_id in blocker.waiting_on_issue_ids:
            notes = origins_by_issue.setdefault(issue_id, [])
            if origin not in notes:
                notes.append(origin)
    for issue_id, notes in origins_by_issue.items():
        if len(direct) >= MAX_NODES:
            diagnostics.append(
                RollRecoveryDiagnostic(
                    code="node_limit_exceeded",
                    node_type="issue",
                    node_id=issue_id,
                    limit=MAX_NODES,
                )
            )
            break
        label = snapshot.issue_labels.get(issue_id, "Required issue")
        direct.append(
            ContinuityBlocker(
                source_type="issue",
                source_id=issue_id,
                source_label=label,
                satisfaction_type="item_read",
                blocker_type="item_unread",
                causing_issue_ids=[issue_id],
                unread_issue_details=[UnreadIssueDetail(issue_id=issue_id, label=label)],
                note="; ".join(notes),
            )
        )
        recommended.setdefault(
            issue_id,
            RollRecoveryPrerequisite(
                node_type="issue",
                node_id=issue_id,
                label=label,
                is_readable=False,
            ),
        )
        for chain in walk(issue_id, frozenset()):
            chains.append(chain)
            for node in chain:
                if node.is_readable:
                    recommended[node.node_id] = RollRecoveryPrerequisite(
                        node_type="issue",
                        node_id=node.node_id,
                        label=node.label,
                        is_readable=True,
                    )
    return RollRecoveryInfo(
        original_thread_id=pending_thread_id,
        original_thread_title=(
            pending_thread_title
            or snapshot.thread_labels.get(pending_thread_id)
            or "Selected series"
        ),
        direct_blockers=direct,
        readable_prerequisites=list(recommended.values()),
        chains=chains,
        diagnostics=diagnostics,
    )
