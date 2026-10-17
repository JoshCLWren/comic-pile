"""Build structured recovery context for blocked pending rolls."""

import logging

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.continuity_chains import resolve_continuity_chains
from app.schemas.roll import (
    RollRecoveryChainNode,
    RollRecoveryDiagnostic,
    RollRecoveryInfo,
    RollRecoveryPrerequisite,
)

from app.services.reading_eligibility_service import get_execution_eligibility
from app.services.reading_recovery_service import build_reading_recovery
from app.repositories.roll_repository import fetch_active_session
from app.services.snooze_service import derive_effective_roll_excluded_thread_ids

logger = logging.getLogger(__name__)


async def build_roll_recovery(
    db: AsyncSession,
    *,
    user_id: int,
    pending_thread_id: int | None,
    pending_thread_title: str | None,
    excluded_thread_ids: frozenset[int] | None = None,
) -> RollRecoveryInfo | None:
    """Return recovery guidance when the preserved pending roll is blocked.

    The pending roll remains the source of truth. This helper explains its
    direct blockers and builds a recommended-prerequisites list that leads
    with the direct blocker(s) (issue #2467).  Readable prerequisite leaves
    follow so the frontend can offer actionable "Read now" CTAs.  A stale
    pending-thread reference is treated as no recovery data so bootstrap can
    still render and let the existing session-reconciliation path recover it.

    Args:
        db: Async database session used for continuity resolution.
        user_id: Authenticated owner of the pending thread.
        pending_thread_id: Preserved pending thread identifier.
        pending_thread_title: Preserved pending thread title, when available.
        excluded_thread_ids: Already-derived session/backoff exclusions, when available.

    Returns:
        Recovery guidance for a blocked pending roll, or ``None``.
    """
    if pending_thread_id is None:
        return None

    eligibility = await get_execution_eligibility(db, user_id)
    if eligibility is not None:
        if excluded_thread_ids is None:
            session = await fetch_active_session(db, user_id)
            excluded_thread_ids = frozenset(
                await derive_effective_roll_excluded_thread_ids(
                    db,
                    user_id,
                    session_snoozed_ids=session.snoozed_thread_ids if session is not None else [],
                    session_skipped_ids=session.skipped_thread_ids if session is not None else [],
                )
            )
        return build_reading_recovery(
            eligibility,
            pending_thread_id=pending_thread_id,
            pending_thread_title=pending_thread_title,
            excluded_thread_ids=excluded_thread_ids,
        )

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
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if exc.status_code == 422 and detail.get("code") == "continuity_graph_too_large":
            logger.warning(
                "Roll recovery unavailable because continuity graph exceeded capacity",
                extra={
                    "user_id": user_id,
                    "pending_thread_id": pending_thread_id,
                    "continuity_error_code": detail.get("code"),
                    "continuity_error_limit": detail.get("limit"),
                },
            )
            return None
        raise

    if not traversal.direct_blockers:
        return None

    # Lead recommendations with direct blockers so the "Read this first"
    # card identifies the same prerequisite issue the blocker explanation
    # names (issue #2467, acceptance criterion 5).  Readable leaves follow
    # and remain the actionable CTA rows when they are reachable.
    recommended: dict[tuple[str, int], RollRecoveryPrerequisite] = {}
    for blocker in traversal.direct_blockers:
        key = (blocker.source_type, blocker.source_id)
        recommended.setdefault(
            key,
            RollRecoveryPrerequisite(
                node_type=blocker.source_type,
                node_id=blocker.source_id,
                label=blocker.source_label,
                is_readable=False,
            ),
        )
    for node in traversal.readable_prerequisites:
        key = (node.node_type, node.node_id)
        recommended[key] = RollRecoveryPrerequisite(
            node_type=node.node_type,
            node_id=node.node_id,
            label=node.label,
            is_readable=node.is_readable,
        )

    return RollRecoveryInfo(
        original_thread_id=pending_thread_id,
        original_thread_title=pending_thread_title or f"Thread {pending_thread_id}",
        direct_blockers=list(traversal.direct_blockers),
        readable_prerequisites=list(recommended.values()),
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
