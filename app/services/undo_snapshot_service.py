"""Undo snapshot service for applying and listing snapshots."""

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Snapshot, Thread
from app.models.session import Session as SessionModel
from app.models.thread import normalize_format_value
from app.repositories.undo_snapshot_repository import UndoSnapshotRepository
from app.schemas import ActiveThreadInfo
from app.services.snapshot_contract import (
    BLOCKED_CHANGES_KEY,
    QUEUE_CHANGES_KEY,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
    USES_ISSUE_TRACKING_KEY,
)
from comic_pile.bandwidth import restore_ephemeral_bandwidth


class UndoSnapshotService:
    """Service for undo snapshot operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service.

        Args:
            db: Database session.
        """
        self.db = db
        self.repository = UndoSnapshotRepository(db)

    def _is_delta_snapshot(self, snapshot: Snapshot) -> bool:
        """Return whether a snapshot uses the version-two delta contract."""
        thread_states = snapshot.thread_states or {}
        return thread_states.get(SNAPSHOT_VERSION_KEY) == SNAPSHOT_VERSION

    async def list_session_snapshots(
        self, session_id: int, session_user_id: int
    ) -> list[Snapshot]:
        """List all snapshots for a session.

        Args:
            session_id: Session whose snapshots should be listed.
            session_user_id: Session owner ID for authorization.

        Returns:
            Snapshot models in reverse chronological order.

        Raises:
            HTTPException: If the session is not found or not owned by user.
        """
        session = await self.repository.get_user_session(session_id, session_user_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found",
            )

        return await self.repository.get_session_snapshots(session_id)

    async def apply_snapshot(
        self, session_id: int, snapshot_id: int, session_user_id: int
    ) -> tuple[SessionModel, dict[str, Any], dict[str, Any]]:
        """Apply a snapshot to restore session state.

        Args:
            session_id: Session to restore.
            snapshot_id: Snapshot to apply.
            session_user_id: Session owner ID.

        Returns:
            Tuple of (session, precomputed_response_values, snapshot_info)

        Raises:
            HTTPException: If snapshot not found or not applicable.
        """
        # Get session and snapshot
        session = await self.repository.get_user_session(
            session_id, session_user_id, for_update=True
        )
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session {session_id} not found",
            )

        snapshot = await self.repository.get_snapshot_by_id(snapshot_id, session_id)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Snapshot {snapshot_id} not found for session {session_id}",
            )

        # Check if this is a delta snapshot and validate
        is_delta = self._is_delta_snapshot(snapshot)
        if is_delta:
            latest_delta = await self.repository.get_latest_delta_snapshot(session_id)
            if latest_delta is None or latest_delta.id != snapshot.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Only the latest rating can be undone",
                )

        # Apply the snapshot
        if is_delta:
            await self._apply_delta_snapshot(session, snapshot)
        else:
            await self._apply_full_snapshot(session, snapshot, session_id)

        # Handle counter-only snapshots - clear issue references for removed threads
        counter_thread_ids = [
            int(thread_id)
            for thread_id, state in (snapshot.thread_states or {}).items()
            if isinstance(state, dict)
            and USES_ISSUE_TRACKING_KEY in state
            and not state[USES_ISSUE_TRACKING_KEY]
        ]
        if counter_thread_ids:
            await self.repository.clear_event_issue_references(session_id, counter_thread_ids)

        # Record undo event
        await self.repository.create_undo_event(session_id, snapshot)
        
        # Delete delta snapshot after applying
        if is_delta:
            await self.repository.delete_snapshot(snapshot_id)

        # Pre-compute response values to avoid post-commit MissingGreenlet errors
        response_values = await self._precompute_response_values(
            session, session_id, is_delta
        )

        return session, response_values, {"is_delta": is_delta, "snapshot_id": snapshot_id}

    async def _apply_full_snapshot(
        self, session: SessionModel, snapshot: Snapshot, session_id: int
    ) -> None:
        """Apply a legacy or session-start full-library snapshot."""
        snapshot_thread_ids = {int(thread_id) for thread_id in snapshot.thread_states}

        # Get current threads and identify which ones to delete
        current_threads = await self.repository.get_user_threads(session.user_id)
        current_thread_ids = {thread.id for thread in current_threads}
        threads_to_delete = current_thread_ids - snapshot_thread_ids

        if threads_to_delete:
            # Clear pending thread references
            await self.repository.update_session_pending_thread_ids(session_id, threads_to_delete)
            
            # Clear event references
            await self.repository.update_event_thread_references(session_id, threads_to_delete)
            
            # Delete threads
            await self.repository.delete_user_threads(session.user_id, threads_to_delete)
            
            # Clear session state to avoid expired object issues
            self.db.expire_all()

        # Bulk-load threads and issues for restoration
        restore_thread_ids = [
            int(tid) for tid in snapshot.thread_states if not str(tid).startswith("_")
        ]
        
        if restore_thread_ids:
            threads_by_id = await self.repository.get_threads_by_ids(restore_thread_ids)
            issues_by_thread = await self.repository.get_issues_by_thread_ids(restore_thread_ids)
        else:
            threads_by_id = {}
            issues_by_thread = {}

        # Restore each thread from snapshot state
        for thread_id_str, state in snapshot.thread_states.items():
            tid = int(thread_id_str)
            await self._restore_thread_from_state(
                tid,
                state,
                session.user_id,
                threads_by_id.get(tid),
                issues_by_thread.get(tid),
            )

        # Restore session state if present
        if snapshot.session_state:
            session.start_die = snapshot.session_state.get("start_die", session.start_die)
            session.manual_die = snapshot.session_state.get("manual_die", session.manual_die)

    async def _apply_delta_snapshot(self, session: SessionModel, snapshot: Snapshot) -> None:
        """Apply only state changed by one version-two rating snapshot."""
        thread_states = snapshot.thread_states or {}
        restore_thread_ids = [
            int(tid) for tid in thread_states if not str(tid).startswith("_")
        ]

        # Bulk-load threads and issues for restoration
        if restore_thread_ids:
            threads_by_id = await self.repository.get_threads_by_ids(restore_thread_ids)
            issues_by_thread = await self.repository.get_issues_by_thread_ids(restore_thread_ids)
        else:
            threads_by_id = {}
            issues_by_thread = {}

        # Restore each thread from snapshot state
        for thread_id, state in thread_states.items():
            if thread_id.startswith("_"):
                continue
            tid = int(thread_id)
            await self._restore_thread_from_state(
                tid,
                state,
                session.user_id,
                threads_by_id.get(tid),
                issues_by_thread.get(tid),
            )

        # Handle queue position changes
        queue_changes = {
            int(thread_id): old_position
            for thread_id, old_position in thread_states.get(QUEUE_CHANGES_KEY, {}).items()
        }
        if queue_changes:
            await self.repository.update_thread_queue_positions(
                session.user_id, queue_changes
            )

        # Handle blocked state changes
        blocked_changes = {
            int(thread_id): old_value
            for thread_id, old_value in thread_states.get(BLOCKED_CHANGES_KEY, {}).items()
        }
        if blocked_changes:
            await self.repository.update_thread_blocked_states(
                session.user_id, blocked_changes
            )

        # Restore session state
        session_state = snapshot.session_state
        if session_state:
            session.start_die = session_state.get("start_die", session.start_die)
            session.manual_die = session_state.get("manual_die", session.manual_die)
            if "pending_thread_id" in session_state:
                session.pending_thread_id = session_state["pending_thread_id"]
            if "pending_thread_updated_at" in session_state:
                session.pending_thread_updated_at = self._deserialize_datetime(
                    session_state["pending_thread_updated_at"]
                )
            if "ended_at" in session_state:
                session.ended_at = self._deserialize_datetime(session_state["ended_at"])
            if "snoozed_thread_ids" in session_state:
                session.snoozed_thread_ids = session_state["snoozed_thread_ids"]
            restore_ephemeral_bandwidth(session, session_state)

    async def _restore_thread_from_state(
        self,
        thread_id: int,
        state: dict,
        session_user_id: int,
        pre_loaded_thread: Thread | None = None,
        pre_loaded_issues: list[Issue] | None = None,
    ) -> None:
        """Restore one thread and its issue state from a snapshot payload."""
        thread = pre_loaded_thread
        if thread is None:
            thread = await self.repository.get_thread_by_id(thread_id)
            if thread is None:
                # Create new thread
                thread = await self.repository.create_thread_from_state(
                    thread_id, state, session_user_id
                )
            else:
                # Update existing thread
                await self.repository.update_thread_from_state(thread, state)
        else:
            # Update existing thread from pre-loaded data
            await self.repository.update_thread_from_state(thread, state)

        # Restore issue states
        await self._restore_issue_states(thread, state, pre_loaded_issues)

    async def _restore_issue_states(
        self, thread: Thread, state: dict, pre_loaded_issues: list[Issue] | None = None
    ) -> None:
        """Restore issue state in place so surviving associations remain intact."""
        has_tracking_marker = USES_ISSUE_TRACKING_KEY in state
        has_issue_payload = "issue_states" in state
        if not has_tracking_marker and not has_issue_payload:
            return

        uses_issue_tracking = state.get(
            USES_ISSUE_TRACKING_KEY,
            state.get("issue_states") is not None,
        )

        if pre_loaded_issues is not None:
            existing_issues = pre_loaded_issues
        else:
            existing_issues = await self.repository.get_issues_by_thread(thread.id)

        thread.next_unread_issue_id = None
        await self.db.flush()

        if not uses_issue_tracking:
            if existing_issues:
                await self.repository.delete_issues_by_ids(
                    [issue.id for issue in existing_issues]
                )
            thread.total_issues = None
            thread.next_unread_issue_id = None
            thread.reading_progress = None
            thread.issues_remaining = state.get(
                "issues_remaining",
                thread.issues_remaining,
            )
            return

        # Restore or create issues with tracking
        snapshot_issues = state.get("issue_states") or []
        snapshot_ids = {int(issue_state["id"]) for issue_state in snapshot_issues}
        existing_by_id = {issue.id: issue for issue in existing_issues}
        extra_ids = [issue.id for issue in existing_issues if issue.id not in snapshot_ids]
        if extra_ids:
            await self.repository.delete_issues_by_ids(extra_ids)

        for fallback_position, issue_state in enumerate(snapshot_issues, start=1):
            issue_id = int(issue_state["id"])
            issue = existing_by_id.get(issue_id)
            if issue is None:
                issue = await self.repository.create_issue_from_state(
                    issue_id, thread.id, issue_state, fallback_position
                )
            else:
                await self.repository.update_issue_from_state(
                    issue, issue_state, fallback_position
                )

        await self.db.flush()
        thread.total_issues = state.get("total_issues")
        thread.next_unread_issue_id = state.get("next_unread_issue_id")
        thread.reading_progress = state.get("reading_progress")
        thread.issues_remaining = state.get(
            "issues_remaining",
            thread.issues_remaining,
        )

    async def _precompute_response_values(
        self, session: SessionModel, session_id: int, is_delta: bool
    ) -> dict[str, Any]:
        """Pre-compute response values to avoid post-commit MissingGreenlet errors."""
        # Combined query: fetch all die-changing events and latest roll event
        all_events = await self.repository.list_session_outcome_events(session_id)

        # Current die from pre-fetched events
        pre_current_die = session.manual_die
        if pre_current_die is None:
            for evt in all_events:
                if evt.type in ("rate", "snooze", "undo") and evt.die_after is not None:
                    pre_current_die = evt.die_after
                    break
            if pre_current_die is None:
                pre_current_die = session.start_die

        # Ladder path from pre-fetched events
        die_events = [
            evt for evt in reversed(all_events)
            if evt.type in ("rate", "snooze", "undo") and evt.die_after is not None
        ]
        pre_ladder_path = str(session.start_die)
        if die_events:
            pre_ladder_path = " → ".join(
                [str(session.start_die)] + [str(evt.die_after) for evt in die_events]
            )

        # Snapshot count: one query regardless of delta/full
        pre_snapshot_count = await self.repository.count_session_snapshots(session_id)
        pre_snapshot_count -= 1 if is_delta else 0

        # Active thread info from pre-fetched events
        pre_active_event = None
        pre_active_info = None
        for evt in all_events:
            if evt.type == "roll" and evt.selected_thread_id is not None:
                pre_active_event = evt
                break

        pre_last_rolled_result = pre_active_event.result if pre_active_event else None
        if pre_active_event and pre_active_event.selected_thread_id:
            pre_thread = await self.repository.get_thread_by_id(
                pre_active_event.selected_thread_id
            )
            if pre_thread is not None:
                # Refresh identity-mapped state before reading it
                await self.db.refresh(pre_thread)
                pre_active_info = ActiveThreadInfo(
                    id=pre_thread.id,
                    title=pre_thread.title,
                    format=normalize_format_value(pre_thread.format),
                    issues_remaining=pre_thread.issues_remaining,
                    queue_position=pre_thread.queue_position,
                    last_rolled_result=pre_active_event.result,
                )

        return {
            "current_die": pre_current_die,
            "ladder_path": pre_ladder_path,
            "snapshot_count": pre_snapshot_count,
            "last_rolled_result": pre_last_rolled_result,
            "active_info": pre_active_info,
        }

    def _deserialize_datetime(self, value: str | None) -> datetime | None:
        """Deserialize an optional ISO datetime value."""
        return datetime.fromisoformat(value) if value else None