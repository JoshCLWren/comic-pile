"""Undo snapshot repository for database operations."""

from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Snapshot, Thread
from app.models.session import Session as SessionModel
from app.models.thread import normalize_format_value
from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY


class UndoSnapshotRepository:
    """Repository for undo snapshot database operations."""

    def __init__(self, db: AsyncSession):
        """Initialize the repository.

        Args:
            db: Database session.
        """
        self.db = db

    async def get_session_snapshots(
        self, session_id: int, order_by_created: bool = True
    ) -> list[Snapshot]:
        """Get all snapshots for a session.

        Args:
            session_id: Session ID to get snapshots for.
            order_by_created: Whether to order by created_at descending.

        Returns:
            List of snapshots.
        """
        query = select(Snapshot).where(Snapshot.session_id == session_id)
        if order_by_created:
            query = query.order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_snapshot_by_id(self, snapshot_id: int, session_id: int) -> Snapshot | None:
        """Get a snapshot by ID scoped to a session.

        Args:
            snapshot_id: Snapshot ID to retrieve.
            session_id: Session the snapshot must belong to.

        Returns:
            Snapshot or None if not found.
        """
        result = await self.db.execute(
            select(Snapshot)
            .where(Snapshot.id == snapshot_id)
            .where(Snapshot.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_delta_snapshot(self, session_id: int) -> Snapshot | None:
        """Get the latest unconsumed delta snapshot for a session.

        Args:
            session_id: Session ID to get snapshot for.

        Returns:
            Latest delta snapshot or None if none exist.
        """
        result = await self.db.execute(
            select(Snapshot)
            .where(Snapshot.session_id == session_id)
            .order_by(Snapshot.created_at.desc(), Snapshot.id.desc())
        )
        snapshots = result.scalars().all()
        
        # Return the first snapshot that is a delta snapshot
        for snapshot in snapshots:
            thread_states = snapshot.thread_states or {}
            if thread_states.get(SNAPSHOT_VERSION_KEY) == SNAPSHOT_VERSION:
                return snapshot
        
        return None

    async def get_user_session(
        self, session_id: int, user_id: int, *, for_update: bool = False
    ) -> SessionModel | None:
        """Get a session owned by a user.

        Args:
            session_id: Session ID to retrieve.
            user_id: User ID who must own the session.
            for_update: Lock the session row to serialize concurrent undo writes.

        Returns:
            Session or None if not found or not owned by user.
        """
        query = (
            select(SessionModel)
            .where(SessionModel.id == session_id)
            .where(SessionModel.user_id == user_id)
        )
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_user_threads(self, user_id: int) -> list[Thread]:
        """Get all threads for a user.

        Args:
            user_id: User ID to get threads for.

        Returns:
            List of threads.
        """
        result = await self.db.execute(select(Thread).where(Thread.user_id == user_id))
        return list(result.scalars().all())

    async def get_threads_by_ids(self, thread_ids: list[int]) -> dict[int, Thread]:
        """Get threads by IDs, returning a mapping of ID to thread.

        Args:
            thread_ids: List of thread IDs to retrieve.

        Returns:
            Dictionary mapping thread ID to Thread.
        """
        if not thread_ids:
            return {}
            
        result = await self.db.execute(select(Thread).where(Thread.id.in_(thread_ids)))
        return {thread.id: thread for thread in result.scalars().all()}

    async def get_issues_by_thread_ids(self, thread_ids: list[int]) -> dict[int, list[Issue]]:
        """Get issues for thread IDs, returning a mapping of thread ID to issues list.

        Args:
            thread_ids: List of thread IDs to get issues for.

        Returns:
            Dictionary mapping thread ID to list of issues.
        """
        if not thread_ids:
            return {}
            
        result = await self.db.execute(
            select(Issue).where(Issue.thread_id.in_(thread_ids)).order_by(Issue.position)
        )
        issues_by_thread = {}
        for issue in result.scalars().all():
            issues_by_thread.setdefault(issue.thread_id, []).append(issue)
        return issues_by_thread

    async def get_event_by_id(self, event_id: int) -> Event | None:
        """Get an event by ID.

        Args:
            event_id: Event ID to retrieve.

        Returns:
            Event or None if not found.
        """
        result = await self.db.execute(select(Event).where(Event.id == event_id))
        return result.scalar_one_or_none()

    async def get_thread_by_id(self, thread_id: int) -> Thread | None:
        """Get a thread by ID.

        Args:
            thread_id: Thread ID to retrieve.

        Returns:
            Thread or None if not found.
        """
        return await self.db.get(Thread, thread_id)

    async def get_issues_by_thread(self, thread_id: int) -> list[Issue]:
        """Get issues for a thread ordered by position.

        Args:
            thread_id: Thread ID to get issues for.

        Returns:
            List of issues ordered by position.
        """
        result = await self.db.execute(
            select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
        )
        return list(result.scalars().all())

    async def delete_issues_by_ids(self, issue_ids: list[int]) -> None:
        """Delete issues by IDs.

        Args:
            issue_ids: List of issue IDs to delete.
        """
        if issue_ids:
            await self.db.execute(delete(Issue).where(Issue.id.in_(issue_ids)))

    async def list_session_outcome_events(self, session_id: int) -> list[Event]:
        """List die-changing and roll events for a session, newest first.

        Args:
            session_id: Session ID to get events for.

        Returns:
            Events of type rate, snooze, undo, or roll in reverse chronological order.
        """
        result = await self.db.execute(
            select(Event)
            .where(Event.session_id == session_id)
            .where(Event.type.in_(("rate", "snooze", "undo", "roll")))
            .order_by(Event.timestamp.desc(), Event.id.desc())
        )
        return list(result.scalars().all())

    async def count_session_snapshots(self, session_id: int) -> int:
        """Count snapshots for a session.

        Args:
            session_id: Session ID to count snapshots for.

        Returns:
            Number of snapshots for the session.
        """
        result = await self.db.execute(
            select(func.count()).select_from(Snapshot).where(Snapshot.session_id == session_id)
        )
        return result.scalar() or 0

    async def delete_snapshot(self, snapshot_id: int) -> None:
        """Delete a snapshot.

        Args:
            snapshot_id: Snapshot ID to delete.
        """
        await self.db.execute(delete(Snapshot).where(Snapshot.id == snapshot_id))

    async def update_session_pending_thread_ids(
        self, session_id: int, thread_ids_to_clear: list[int]
    ) -> None:
        """Clear pending_thread_id for specified threads in a session.

        Args:
            session_id: Session ID to update.
            thread_ids_to_clear: List of thread IDs to clear.
        """
        if thread_ids_to_clear:
            await self.db.execute(
                update(SessionModel)
                .where(SessionModel.id == session_id)
                .where(SessionModel.pending_thread_id.in_(thread_ids_to_clear))
                .values(pending_thread_id=None)
            )

    async def update_event_thread_references(
        self, session_id: int, thread_ids_to_clear: list[int]
    ) -> None:
        """Clear thread references in events for specified thread IDs.

        Args:
            session_id: Session ID to update events for.
            thread_ids_to_clear: List of thread IDs to clear references for.
        """
        if thread_ids_to_clear:
            await self.db.execute(
                update(Event)
                .where(Event.session_id == session_id)
                .where(
                    Event.thread_id.in_(thread_ids_to_clear)
                    | Event.selected_thread_id.in_(thread_ids_to_clear)
                )
                .values(
                    thread_id=None,
                    selected_thread_id=None,
                    issue_id=None,  # Also clear issue_id for counter snapshots
                )
            )

    async def clear_event_issue_references(
        self, session_id: int, thread_ids_to_clear: list[int]
    ) -> None:
        """Clear issue references for counter-only threads without dropping thread links.

        Counter-only snapshots predate issue tracking. Their restored state has no
        issue identity, so rate events from the undone session must not retain foreign
        keys to issues just removed, while the thread references stay intact.

        Args:
            session_id: Session ID to update events for.
            thread_ids_to_clear: List of thread IDs to clear issue references for.
        """
        if thread_ids_to_clear:
            await self.db.execute(
                update(Event)
                .where(Event.session_id == session_id)
                .where(Event.thread_id.in_(thread_ids_to_clear))
                .values(issue_id=None)
            )

    async def delete_user_threads(self, user_id: int, thread_ids: list[int]) -> None:
        """Delete threads for a user.

        Args:
            user_id: User ID who owns the threads.
            thread_ids: List of thread IDs to delete.
        """
        if thread_ids:
            await self.db.execute(
                delete(Thread)
                .where(Thread.id.in_(thread_ids))
                .where(Thread.user_id == user_id)
            )

    async def update_thread_queue_positions(
        self, user_id: int, queue_changes: dict[int, int]
    ) -> None:
        """Update thread queue positions based on queue changes.

        Args:
            user_id: User ID who owns the threads.
            queue_changes: Dictionary mapping thread ID to old queue position.
        """
        if queue_changes:
            from sqlalchemy import case
            
            await self.db.execute(
                update(Thread)
                .where(Thread.user_id == user_id)
                .where(Thread.id.in_(queue_changes.keys()))
                .values(
                    queue_position=case(
                        queue_changes,
                        value=Thread.id,
                        else_=Thread.queue_position,
                    )
                )
            )

    async def update_thread_blocked_states(
        self, user_id: int, blocked_changes: dict[int, bool]
    ) -> None:
        """Update thread blocked states based on blocked changes.

        Args:
            user_id: User ID who owns the threads.
            blocked_changes: Dictionary mapping thread ID to old blocked state.
        """
        if blocked_changes:
            from sqlalchemy import case
            
            await self.db.execute(
                update(Thread)
                .where(Thread.user_id == user_id)
                .where(Thread.id.in_(blocked_changes.keys()))
                .values(
                    is_blocked=case(
                        blocked_changes,
                        value=Thread.id,
                        else_=Thread.is_blocked,
                    )
                )
            )

    async def create_thread_from_state(
        self, thread_id: int, state: dict, session_user_id: int
    ) -> Thread:
        """Create a new thread from snapshot state.

        Args:
            thread_id: Thread ID to create.
            state: Snapshot state for the thread.
            session_user_id: Session owner ID.

        Returns:
            Created thread.
        """
        thread = Thread(
            id=thread_id,
            title=state.get("title", "Unknown Thread"),
            format=normalize_format_value(state.get("format", "comic")),
            issues_remaining=state.get("issues_remaining", 0),
            last_rating=state.get("last_rating"),
            queue_position=state.get("queue_position", 1),
            status=state.get("status", "active"),
            notes=state.get("notes"),
            is_test=state.get("is_test", False),
            is_blocked=state.get("is_blocked", False),
            user_id=state.get("user_id", session_user_id),
            created_at=self._deserialize_datetime(state.get("created_at"))
            or datetime.now(UTC),
        )
        thread.last_activity_at = self._deserialize_datetime(state.get("last_activity_at"))
        
        self.db.add(thread)
        await self.db.flush()
        return thread

    async def update_thread_from_state(self, thread: Thread, state: dict) -> None:
        """Update an existing thread from snapshot state.

        Args:
            thread: Thread to update.
            state: Snapshot state for the thread.
        """
        if "title" in state:
            thread.title = state["title"]
        if "format" in state:
            thread.format = normalize_format_value(state["format"])
        if "issues_remaining" in state:
            thread.issues_remaining = state["issues_remaining"]
        if "last_rating" in state:
            thread.last_rating = state["last_rating"]
        if "queue_position" in state:
            thread.queue_position = state["queue_position"]
        if "status" in state:
            thread.status = state["status"]
        if "notes" in state:
            thread.notes = state["notes"]
        if "is_test" in state:
            thread.is_test = state["is_test"]
        if "is_blocked" in state:
            thread.is_blocked = state["is_blocked"]
        if "last_activity_at" in state:
            thread.last_activity_at = self._deserialize_datetime(state.get("last_activity_at"))

    async def create_issue_from_state(
        self,
        issue_id: int,
        thread_id: int,
        issue_state: dict,
        fallback_position: int,
    ) -> Issue:
        """Create a new issue from snapshot state.

        Args:
            issue_id: Issue ID to create.
            thread_id: Thread ID the issue belongs to.
            issue_state: Snapshot state for the issue.
            fallback_position: Sequential position when the state omits one.

        Returns:
            Created issue.
        """
        issue = Issue(
            id=issue_id,
            thread_id=thread_id,
            issue_number=issue_state["number"],
            status=issue_state["status"],
            read_at=self._deserialize_datetime(issue_state.get("read_at")),
            position=issue_state.get("position", fallback_position),
        )
        
        self.db.add(issue)
        await self.db.flush()
        return issue

    async def update_issue_from_state(
        self, issue: Issue, issue_state: dict, fallback_position: int
    ) -> None:
        """Update an existing issue from snapshot state.

        Args:
            issue: Issue to update.
            issue_state: Snapshot state for the issue.
            fallback_position: Sequential position when the state omits one.
        """
        issue.issue_number = issue_state["number"]
        issue.status = issue_state["status"]
        issue.read_at = self._deserialize_datetime(issue_state.get("read_at"))
        issue.position = issue_state.get("position", fallback_position)

    async def create_undo_event(
        self, session_id: int, snapshot: Snapshot
    ) -> Event:
        """Create an undo event for a snapshot.

        Args:
            session_id: Session ID to create event for.
            snapshot: Snapshot being undone.

        Returns:
            Created event.
        """
        target_event = (
            await self.db.get(Event, snapshot.event_id)
            if snapshot.event_id is not None
            else None
        )
        restored_die = None
        if snapshot.session_state:
            restored_die = snapshot.session_state.get("current_die")
        if restored_die is None and target_event is not None:
            restored_die = target_event.die

        event = Event(
            type="undo",
            session_id=session_id,
            thread_id=target_event.thread_id if target_event else None,
            die=target_event.die_after if target_event else None,
            die_after=restored_die,
        )
        
        self.db.add(event)
        return event

    def _deserialize_datetime(self, value: str | None) -> datetime | None:
        """Deserialize an optional ISO datetime value."""
        return datetime.fromisoformat(value) if value else None