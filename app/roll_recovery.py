"""Build structured recovery context for blocked pending rolls."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_chains import resolve_continuity_chains
from app.schemas.roll import (
    RollRecoveryChainNode,
    RollRecoveryDiagnostic,
    RollRecoveryInfo,
    RollRecoveryPrerequisite,
)


async def build_roll_recovery(
    db: AsyncSession,
    *,
    user_id: int,
    pending_thread_id: int | None,
    pending_thread_title: str | None,
) -> RollRecoveryInfo | None:
    """Return recovery guidance when the preserved pending roll is blocked.

    The pending roll remains the source of truth. This helper only explains its
    direct blockers and recommends currently readable prerequisite leaves from
    the canonical continuity traversal. A stale pending-thread reference is
    treated as no recovery data so bootstrap can still render and let the
    existing session-reconciliation path recover it.

    Args:
        db: Async database session used for continuity resolution.
        user_id: Authenticated owner of the pending thread.
        pending_thread_id: Preserved pending thread identifier.
        pending_thread_title: Preserved pending thread title, when available.

    Returns:
        Recovery guidance for a blocked pending roll, or ``None``.
    """
    if pending_thread_id is None:
        return None

    try:
        traversal = await resolve_continuity_chains(
            db,
            user_id=user_id,
            node_type="thread",
            node_id=pending_thread_id,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise

    if not traversal.direct_blockers:
        return None

    return RollRecoveryInfo(
        original_thread_id=pending_thread_id,
        original_thread_title=pending_thread_title or f"Thread {pending_thread_id}",
        direct_blockers=list(traversal.direct_blockers),
        readable_prerequisites=[
            RollRecoveryPrerequisite(
                node_type=node.node_type,
                node_id=node.node_id,
                label=node.label,
            )
            for node in traversal.readable_prerequisites
        ],
        chains=[
            [
                RollRecoveryChainNode(
                    node_type=node.node_type,
                    node_id=node.node_id,
                    label=node.label,
                    is_readable=node.is_readable,
                )
                for node in chain
            ]
            for chain in traversal.chains
        ],
        diagnostics=[
            RollRecoveryDiagnostic(
                code=diagnostic.code,
                node_type=diagnostic.node_type,
                node_id=diagnostic.node_id,
                limit=diagnostic.limit,
            )
            for diagnostic in traversal.diagnostics
        ],
    )
