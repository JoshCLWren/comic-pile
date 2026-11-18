"""Session API endpoints."""

from __future__ import annotations

from typing import TypedDict

from fastapi import APIRouter

from app.schemas import SessionListItem, SessionResponse

router = APIRouter(tags=["sessions"])
#: Versioned-only surface for new session client resources. ``app.main`` mounts
#: this router *before* :data:`router` at the ``/api/v1/sessions`` prefix so a
#: literal path always wins over the ``/{session_id}`` parameter route, and it
#: is never mounted under bare ``/api/*`` (see docs/API.md and the convention
#: comment in app/main.py).
v1_router = APIRouter(tags=["sessions"])


class _RateAggregate(TypedDict):
    """Aggregated rating-event state for one session history row."""

    issues_read: int
    last_rating: float | None


def _to_session_list_item(sr: SessionResponse) -> SessionListItem:
    """Convert a full SessionResponse to a narrow SessionListItem.

    Deliberately drops snoozed_thread_ids, snoozed_threads, and pending_thread_id
    to reduce payload size for session history list views.
    """
    return SessionListItem(
        id=sr.id,
        started_at=sr.started_at,
        ended_at=sr.ended_at,
        start_die=sr.start_die,
        manual_die=sr.manual_die,
        user_id=sr.user_id,
        ladder_path=sr.ladder_path,
        active_thread=sr.active_thread,
        current_die=sr.current_die,
        last_rolled_result=sr.last_rolled_result,
        has_restore_point=sr.has_restore_point,
        snapshot_count=sr.snapshot_count,
    )
