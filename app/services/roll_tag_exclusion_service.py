"""Persistent account-wide Roll tag exclusions (issue #3033).

Services own business rules and transaction boundaries. Query construction
lives in ``app.repositories.roll_tag_exclusion_repository``. HTTP status
mapping lives in routers.

Exclusions are eligibility constraints only. Adding, removing, or triggering
an exclusion must never snooze a thread, change the die, feed bandwidth
correction, move queue positions, or affect ratings and recommendation
weighting.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tag, User
from app.repositories import roll_tag_exclusion_repository, tag_repository
from app.schemas import RollResponse
from app.services.errors import NotFoundError
from app.services.tag_service import TagDeletionHook, register_tag_deletion_hook


@dataclass
class ExcludeTagAndRerollResult:
    """Outcome of excluding a tag mid-roll with neutral auto-reroll.

    Attributes:
        excluded_tag: The tag that was persistently excluded.
        pending_invalidated: ``True`` when the pending roll became ineligible
            under the new exclusion, was cleared, and was replaced through
            normal Roll selection.
        roll: The replacement roll when ``pending_invalidated`` is ``True``,
            otherwise ``None`` (no pending roll existed, or it stayed
            eligible).
    """

    excluded_tag: Tag
    pending_invalidated: bool
    roll: RollResponse | None = None


@dataclass
class PoolTagExclusionState:
    """Tag-exclusion state for one roll-pool evaluation.

    Attributes:
        excluded_tags: The user's active excluded tags.
        ineligible_tag_ids: Map from each excluded candidate thread ID to the
            sorted excluded tag IDs responsible, derived from the candidate's
            next unread issue effective tags.
    """

    excluded_tags: list[Tag]
    ineligible_tag_ids: dict[int, list[int]]


class RollTagExclusionService:
    """Business logic for persistent account-wide Roll tag exclusions.

    Exclusions are user-scoped: a private exclusion references a global tag
    or a private tag owned by the same user, and it hides matching candidates
    only for the excluding user. Global tags may be excluded per user without
    affecting anyone else.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the exclusion service.

        Args:
            db: Database session.
        """
        self._db = db

    async def list_excluded_tags(self, user: User) -> list[Tag]:
        """Return the tags one user excluded from Roll eligibility.

        Only tags visible to the user are returned: every global tag plus the
        user's own private tags. A private tag owned by someone else can never
        appear, so private vocabulary never leaks across users.

        Args:
            user: The requesting user.

        Returns:
            Excluded tags ordered by scope then normalized name.
        """
        tags = await roll_tag_exclusion_repository.list_excluded_tags(
            self._db, user.id
        )
        return [
            tag
            for tag in tags
            if tag.scope == "global" or tag.owner_user_id == user.id
        ]

    async def add_exclusion(self, user: User, tag_id: int) -> Tag:
        """Persist one user's exclusion of one tag.

        The operation is idempotent: excluding an already-excluded tag returns
        the tag unchanged. Persisting an exclusion has no snooze, backoff,
        bandwidth, rating, or recommendation side effects.

        Args:
            user: The requesting user.
            tag_id: Tag to exclude from Roll eligibility.

        Returns:
            The excluded tag.

        Raises:
            NotFoundError: When the tag does not exist or is not visible to
                the user (global tags are visible to everyone; private tags
                only to their owner).
        """
        tag = await self._require_visible_tag(user, tag_id)
        tag_id_value = tag.id
        await roll_tag_exclusion_repository.add_exclusion(
            self._db, user.id, tag_id_value
        )
        await self._db.commit()
        return tag

    async def remove_exclusion(self, user: User, tag_id: int) -> Tag:
        """Remove one user's exclusion of one tag.

        Removing an exclusion makes matching candidates eligible immediately.

        Args:
            user: The requesting user.
            tag_id: Tag to stop excluding.

        Returns:
            The formerly excluded tag.

        Raises:
            NotFoundError: When the tag does not exist, is not visible to the
                user, or is not currently excluded by the user.
        """
        tag = await self._require_visible_tag(user, tag_id)
        removed = await roll_tag_exclusion_repository.remove_exclusion(
            self._db, user.id, tag.id
        )
        if not removed:
            raise NotFoundError(f"Tag {tag.id} is not excluded from Roll")
        await self._db.commit()
        return tag

    async def _require_visible_tag(self, user: User, tag_id: int) -> Tag:
        """Return a tag visible to the user or raise NotFoundError.

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.

        Returns:
            The visible tag.

        Raises:
            NotFoundError: When the tag does not exist or is a private tag
                owned by someone else. Both cases report "does not exist" so
                private vocabulary never leaks across users.
        """
        tag = await tag_repository.get_tag_by_id(self._db, tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist")
        if tag.scope == "private" and tag.owner_user_id != user.id:
            raise NotFoundError(f"Tag {tag_id} does not exist")
        return tag

    async def get_pool_exclusion_state(
        self, user: User, candidates: list[tuple[int, int | None]]
    ) -> PoolTagExclusionState:
        """Evaluate tag exclusions for many roll candidates in bulk.

        Each candidate is a ``(thread_id, next_unread_issue_id)`` pair. A
        candidate is ineligible when its next unread issue's effective tags
        (direct plus inherited private/global tags) contain any excluded tag.
        Effective tags resolve in a constant number of round trips, never one
        tag lookup per candidate.

        Args:
            user: The requesting user.
            candidates: ``(thread_id, next_unread_issue_id)`` pairs. A ``None``
                issue ID means the thread has no tracked next issue, so only
                its thread tags contribute.

        Returns:
            The active excluded tags plus the ineligible thread map.
        """
        excluded_tags = await self.list_excluded_tags(user)
        if not excluded_tags or not candidates:
            return PoolTagExclusionState(
                excluded_tags=excluded_tags, ineligible_tag_ids={}
            )
        excluded_ids = {tag.id for tag in excluded_tags}
        effective = await roll_tag_exclusion_repository.fetch_effective_tag_ids_for_candidates(
            self._db, user.id, candidates
        )
        ineligible: dict[int, list[int]] = {}
        for thread_id, _ in candidates:
            matching = sorted(excluded_ids & effective.get(thread_id, set()))
            if matching:
                ineligible[thread_id] = matching
        return PoolTagExclusionState(
            excluded_tags=excluded_tags, ineligible_tag_ids=ineligible
        )


class RollTagExclusionDeletionHook(TagDeletionHook):
    """Tag-deletion consumer that cleans up Roll exclusion references.

    Deleting a tag removes every user's exclusion of it, so the deleted tag
    stops filtering Roll pools. This is the roll-filter consumer the tag
    usage endpoint anticipates: usage previews count these references before
    deletion, and deletion reports how many were removed.
    """

    @property
    def consumer_name(self) -> str:
        """Return the stable consumer name for deletion reports."""
        return "roll_tag_exclusions"

    async def cleanup_tag_references(self, db: AsyncSession, tag_id: int) -> int:
        """Remove every exclusion referencing a deleted tag.

        Args:
            db: Database session.
            tag_id: Primary key of the deleted tag.

        Returns:
            Number of exclusion rows removed.
        """
        return await roll_tag_exclusion_repository.delete_exclusions_for_tag(
            db, tag_id
        )

    async def count_tag_references(self, db: AsyncSession, tag_id: int) -> int:
        """Count exclusion rows referencing a tag without removing them.

        Args:
            db: Database session.
            tag_id: Primary key of the tag.

        Returns:
            Number of exclusion rows referencing the tag.
        """
        return await roll_tag_exclusion_repository.count_exclusions_for_tag(
            db, tag_id
        )


register_tag_deletion_hook(RollTagExclusionDeletionHook())
