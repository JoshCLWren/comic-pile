"""Tag business logic.

Services own normalization, duplicate and near-match handling, color
validation, authorization rules, target existence/ownership validation,
assignment management, and deletion cascades. HTTP status mapping lives in the
routers.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_TAG_COLOR_NAME,
    NEAR_MATCH_DISTANCE,
    NEAR_MATCH_LIMIT,
    TAG_TARGET_TYPES,
    validate_tag_color,
)
from app.models import ContinuityPlan, Issue, Tag, TagAssignment, Thread, User
from app.repositories import tag_repository
from app.schemas.tags import TagScope
from app.services.errors import ConflictError, ForbiddenError, InvalidRequestError, NotFoundError


@dataclass
class CreateTagResult:
    """Result of a tag creation request.

    Attributes:
        tag: The resulting tag (either newly created or the existing global
            tag the request was redirected to).
        redirected_to_global: ``True`` when a private-tag creation request
            matched an existing global tag by normalized name and was
            redirected to that global tag instead of creating a duplicate.
        near_matches: Global tags whose names are near matches to the requested
            name. Empty by default; populated on request.
    """

    tag: Tag
    redirected_to_global: bool = False
    near_matches: list[Tag] = field(default_factory=list)


@dataclass
class DeleteTagResult:
    """Result of a tag deletion.

    Attributes:
        tag: The deleted tag.
        assignments_removed: Number of ``tag_assignments`` rows deleted.
        references_removed_by_consumers: Per-consumer counts of roll-filter or
            other tag references removed by registered deletion hook
            consumers. Roll filtering has no consumer yet, so this is empty.
    """

    tag: Tag
    assignments_removed: int
    references_removed_by_consumers: dict[str, int] = field(default_factory=dict)


# Loads one polymorphic target row by primary key, or ``None`` when
# the target does not exist. Loaders must issue explicit queries and
# must never lazy-load relationships inside an async session.
TargetLoader = Callable[
    [AsyncSession, int], Awaitable[Issue | Thread | ContinuityPlan | None]
]


class TargetValidator:
    """Validation for one polymorphic target type.

    Attributes:
        type_name: The ``target_type`` value this validator handles.
    """

    def __init__(self, type_name: str, loader: TargetLoader) -> None:
        """Initialize a target validator.

        Args:
            type_name: The ``target_type`` value this validator handles.
            loader: Async callable that loads a target row by id.
        """
        self.type_name = type_name
        self._loader = loader

    async def load(
        self, db: AsyncSession, target_id: int
    ) -> Issue | Thread | ContinuityPlan | None:
        """Load the target row for this validator's type.

        Args:
            db: Database session.
            target_id: Primary key of the target.

        Returns:
            The target row, or ``None`` when it does not exist.
        """
        return await self._loader(db, target_id)


async def _load_issue(
    db: AsyncSession, target_id: int
) -> Issue | None:
    """Load an issue by primary key.

    Args:
        db: Database session.
        target_id: Primary key of the issue.

    Returns:
        The issue, or ``None`` when it does not exist.
    """
    result = await db.execute(select(Issue).where(Issue.id == target_id))
    return result.scalar_one_or_none()


async def _load_thread(
    db: AsyncSession, target_id: int
) -> Thread | None:
    """Load a thread by primary key.

    Args:
        db: Database session.
        target_id: Primary key of the thread.

    Returns:
        The thread, or ``None`` when it does not exist.
    """
    result = await db.execute(select(Thread).where(Thread.id == target_id))
    return result.scalar_one_or_none()


async def _load_continuity_plan(
    db: AsyncSession, target_id: int
) -> ContinuityPlan | None:
    """Load a reading plan by primary key.

    Args:
        db: Database session.
        target_id: Primary key of the reading plan.

    Returns:
        The reading plan, or ``None`` when it does not exist.
    """
    result = await db.execute(
        select(ContinuityPlan).where(ContinuityPlan.id == target_id)
    )
    return result.scalar_one_or_none()


# Registry of target validators keyed by ``target_type``.
_target_validators: dict[str, TargetValidator] = {}


def register_target_validator(type_name: str, loader: TargetLoader) -> None:
    """Register a validator for a polymorphic target type.

    Args:
        type_name: The ``target_type`` value this validator handles.
        loader: Async callable that loads a target row by id.
    """
    _target_validators[type_name] = TargetValidator(type_name, loader)


register_target_validator("Issue", _load_issue)
register_target_validator("Thread", _load_thread)
register_target_validator("ContinuityPlan", _load_continuity_plan)


def _get_target_validator(type_name: str) -> TargetValidator:
    """Return the validator for a target type.

    Args:
        type_name: The target type name.

    Raises:
        InvalidRequestError: When ``type_name`` is not a registered type.
    """
    validator = _target_validators.get(type_name)
    if validator is None:
        raise InvalidRequestError(
            f"Unsupported target type '{type_name}'. Supported types: "
            f"{', '.join(TAG_TARGET_TYPES)}"
        )
    return validator


async def _validate_target(
    db: AsyncSession, user: User, target_type: str, target_id: int, *, enforce_ownership: bool
) -> None:
    """Validate that a polymorphic target exists and is visible to the user.

    ``enforce_ownership`` is ``True`` for private tags: the tag owner may only
    attach their own tag to a target they own, so a private vocabulary can
    never be pushed onto another user's object. It is ``False`` for global
    tags, which only administrators may assign and which must be assignable to
    any existing target. Issue ownership is resolved through the owning thread
    with an explicit query so no relationship is ever lazy-loaded inside the
    async session.

    Args:
        db: Database session.
        user: The requesting user.
        target_type: The target type.
        target_id: The target primary key.
        enforce_ownership: Whether the user must own the target.

    Raises:
        NotFoundError: When the target does not exist.
        ForbiddenError: When the user does not own the target and ownership is
            enforced.
    """
    validator = _get_target_validator(target_type)
    target = await validator.load(db, target_id)
    if target is None:
        raise NotFoundError(
            f"{target_type} with id {target_id} does not exist"
        )

    if not enforce_ownership:
        return

    if isinstance(target, Issue):
        owner_row = await db.execute(
            select(Thread.user_id).where(Thread.id == target.thread_id)
        )
        owner_id = owner_row.scalar_one_or_none()
    else:
        owner_id = target.user_id

    if owner_id != user.id:
        raise ForbiddenError(
            "You may only assign private tags to targets you own"
        )


async def purge_target_assignments(
    db: AsyncSession, target_type: str, target_ids: Iterable[int]
) -> int:
    """Remove assignments that point at targets being deleted.

    Polymorphic ``target_id`` values carry no foreign key, so every path that
    deletes a taggable target must call this before the delete to avoid
    dangling assignments.

    Args:
        db: Database session.
        target_type: Type of the deleted target.
        target_ids: Primary keys of the deleted target rows.

    Returns:
        Number of assignment rows removed.
    """
    return await tag_repository.delete_assignments_for_target(
        db, target_type, target_ids
    )


class TagDeletionHook:
    """Consumer of tag deletion events.

    Subclass or implement this protocol to have references removed from a tag
    consumer (e.g. roll filters / exclusions) when a tag is deleted.
    """

    @property
    def consumer_name(self) -> str:
        """A stable name for this consumer, used in deletion reports."""
        return type(self).__name__

    async def cleanup_tag_references(self, db: AsyncSession, tag_id: int) -> int:
        """Remove references to a tag held by this consumer.

        Args:
            db: Database session.
            tag_id: Primary key of the deleted tag.

        Returns:
            Number of references removed. Roll filtering has no consumer yet,
            so implementations should return 0 in v1.
        """
        del db, tag_id
        return 0


# Registry of tag deletion hook consumers.
_tag_deletion_hooks: list[TagDeletionHook] = []


def register_tag_deletion_hook(hook: TagDeletionHook) -> None:
    """Register a consumer that cleans up references when a tag is deleted.

    Args:
        hook: The deletion hook consumer.
    """
    if hook in _tag_deletion_hooks:
        return
    _tag_deletion_hooks.append(hook)


def unregister_tag_deletion_hook(hook: TagDeletionHook) -> None:
    """Remove a previously registered deletion hook consumer.

    Args:
        hook: The deletion hook consumer to remove.
    """
    if hook in _tag_deletion_hooks:
        _tag_deletion_hooks.remove(hook)


class TagService:
    """Business logic for the tag domain.

    The service enforces the privacy boundary (global tags visible to all,
    private tags visible only to their owner), admin-only mutation of global
    tags, normalized duplicate detection, near-match suggestions, strict color
    palette validation, and polymorphic target validation.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the tag service.

        Args:
            db: Database session.
        """
        self._db = db

    # ---------------------------------------------------------------------
    # Normalization and color
    # ---------------------------------------------------------------------

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize a tag name for matching.

        Trims surrounding whitespace and lowercases the result. The original
        casing is preserved in the stored ``name`` column and returned as
        displayed.

        Args:
            name: Raw tag name.

        Returns:
            Normalized name.
        """
        return tag_repository.normalize_tag_name(name)

    @staticmethod
    def _require_global_scope_admin(user: User, action: str) -> None:
        """Refuse a global-tag mutation from a non-administrator.

        Args:
            user: The requesting user.
            action: Human-readable action used in the error message.

        Raises:
            ForbiddenError: When the user is not an administrator.
        """
        if not user.is_admin:
            raise ForbiddenError(f"Only administrators can {action} global tags")

    def validate_color(self, color: object) -> tuple[str, str]:
        """Validate a color and return ``(name, hex)``.

        Args:
            color: A palette name or hex value.

        Returns:
            Tuple of ``(color_name, color_hex)``.

        Raises:
            InvalidRequestError: When the color is not in the fixed palette.
        """
        try:
            return validate_tag_color(color)
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from exc

    # ---------------------------------------------------------------------
    # Listing and retrieval
    # ---------------------------------------------------------------------

    async def list_tags(self, user: User) -> list[Tag]:
        """Return all tags visible to a user.

        Global tags are visible to everyone; a user also sees their own
        private tags.

        Args:
            user: The requesting user.

        Returns:
            List of visible tags.
        """
        return await tag_repository.list_tags_for_user(self._db, user.id)

    async def get_tag(self, user: User, tag_id: int) -> Tag:
        """Return a tag, enforcing visibility.

        Global tags are visible to any authenticated user. Private tags are
        visible only to their owner; every other caller, administrators
        included, is told the tag does not exist so private vocabulary never
        leaks across users.

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.

        Returns:
            The visible tag.

        Raises:
            NotFoundError: When the tag does not exist or is not visible.
        """
        tag = await tag_repository.get_tag_by_id(self._db, tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist")

        if tag.scope == TagScope.PRIVATE and tag.owner_user_id != user.id:
            raise NotFoundError(f"Tag {tag_id} does not exist")

        return tag

    # ---------------------------------------------------------------------
    # Creation
    # ---------------------------------------------------------------------

    async def create_tag(
        self,
        user: User,
        name: str,
        color: str | None = None,
        *,
        scope: TagScope | str | None = None,
        include_near_matches: bool = False,
    ) -> CreateTagResult:
        """Create a tag or return an existing global tag.

        Non-admin users can only create private tags. When a private-tag
        creation request matches an existing global tag by normalized name,
        the existing global tag is returned instead of creating a private
        duplicate. Admins may create global tags explicitly.

        Args:
            user: The requesting user.
            name: Raw tag name.
            color: Palette name or hex color value; defaults to red.
            scope: ``"global"`` (admin only) or ``"private"``; defaults to
                private for non-admins.
            include_near_matches: When ``True``, compute near matches.

        Returns:
            The CreateTagResult describing what happened.

        Raises:
            ForbiddenError: When a non-admin requests a global tag.
            InvalidRequestError: When the color is invalid, the name is empty,
                or the scope is unknown.
            ConflictError: When the normalized name already exists as a
                global tag or as another private tag of the same user.
        """
        normalized = self.normalize_name(name)
        if not normalized:
            raise InvalidRequestError("Tag name cannot be empty")

        color_name, color_hex = self.validate_color(color or DEFAULT_TAG_COLOR_NAME)

        # Determine the effective scope.
        if scope is None:
            effective_scope = TagScope.PRIVATE.value
        elif scope == TagScope.GLOBAL:
            if not user.is_admin:
                raise ForbiddenError("Only administrators can create global tags")
            effective_scope = TagScope.GLOBAL.value
        elif scope == TagScope.PRIVATE:
            effective_scope = TagScope.PRIVATE.value
        else:
            raise InvalidRequestError(f"Unknown tag scope '{scope}'")

        # Exact match against a global tag redirects to it instead of creating
        # a private duplicate.
        existing_global = await tag_repository.get_tag_by_name(
            self._db, normalized, TagScope.GLOBAL.value
        )
        if existing_global is not None:
            return CreateTagResult(
                tag=existing_global,
                redirected_to_global=True,
                near_matches=[],
            )

        # Compute near matches on request.
        near_matches: list[Tag] = []
        if include_near_matches:
            near_matches = await tag_repository.find_nearly_matching_global_tags(
                self._db,
                normalized,
                max_distance=NEAR_MATCH_DISTANCE,
                limit=NEAR_MATCH_LIMIT,
            )

        tag = Tag(
            name=name,
            normalized_name=normalized,
            scope=effective_scope,
            owner_user_id=(
                user.id if effective_scope == TagScope.PRIVATE.value else None
            ),
            color=color_hex,
        )
        try:
            created = await tag_repository.create_tag(self._db, tag)
        except IntegrityError as exc:
            # The unique indexes reject a duplicate global name or a
            # second private tag with the same normalized name for one
            # user; report it as a conflict instead of a server error.
            raise ConflictError("A tag with this name already exists") from exc
        return CreateTagResult(
            tag=created,
            near_matches=near_matches,
        )

    # ---------------------------------------------------------------------
    # Update
    # ---------------------------------------------------------------------

    async def update_tag(
        self,
        user: User,
        tag_id: int,
        *,
        name: str | None = None,
        color: str | None = None,
    ) -> Tag:
        """Update an existing tag.

        Global tags require admin access. Private tags require ownership: a
        private tag is invisible to everyone but its owner, administrators
        included. Renaming a private tag to a normalized name already used by a
        global tag is refused to avoid vocabulary collision.

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.
            name: New display name; ``None`` to leave unchanged.
            color: New palette name or hex color; ``None`` to leave unchanged.

        Returns:
            The updated tag.

        Raises:
            NotFoundError: When the tag does not exist or is not visible.
            ForbiddenError: When the user lacks permission.
            InvalidRequestError: When the color is invalid or the name is empty.
            ConflictError: When the new name collides with a global tag.
        """
        tag = await self.get_tag(user, tag_id)

        if tag.scope == TagScope.GLOBAL.value:
            self._require_global_scope_admin(user, "edit")
        elif tag.owner_user_id != user.id:
            raise ForbiddenError("You can only edit your own private tags")

        updates: list[tuple[str, object]] = []
        if name is not None:
            normalized = self.normalize_name(name)
            if not normalized:
                raise InvalidRequestError("Tag name cannot be empty")
            if normalized != tag.normalized_name:
                existing = await tag_repository.get_tag_by_name(
                    self._db, normalized, TagScope.GLOBAL.value
                )
                if existing is not None:
                    raise ConflictError(
                        f"A global tag named '{name}' already exists"
                    )
            updates.append(("name", name))
            updates.append(("normalized_name", normalized))

        if color is not None:
            name_out, hex_out = self.validate_color(color)
            updates.append(("color", hex_out))

        if updates:
            for attr, value in updates:
                setattr(tag, attr, value)
            tag.updated_at = await self._now()
            tag = await tag_repository.update_tag(self._db, tag)

        return tag

    # ---------------------------------------------------------------------
    # Deletion
    # ---------------------------------------------------------------------

    async def delete_tag(
        self,
        user: User,
        tag_id: int,
    ) -> DeleteTagResult:
        """Delete a tag and cascade its assignments.

        Global tags require admin access. Private tags require ownership: a
        private tag is invisible to everyone but its owner, administrators
        included. Deletion removes all ``tag_assignments`` rows and runs
        registered deletion hook consumers (used by roll-filter and exclusion
        modules once they exist).

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.

        Returns:
            The DeleteTagResult with usage statistics.

        Raises:
            NotFoundError: When the tag does not exist or is not visible.
            ForbiddenError: When the user lacks permission.
        """
        tag_id_value = tag_id
        tag = await self.get_tag(user, tag_id_value)

        if tag.scope == TagScope.GLOBAL.value:
            self._require_global_scope_admin(user, "delete")
        elif tag.owner_user_id != user.id:
            raise ForbiddenError("You can only delete your own private tags")

        assignments_removed = await tag_repository.delete_tag_assignments(
            self._db, tag_id_value
        )

        references_removed_by_consumers: dict[str, int] = {}
        for hook in _tag_deletion_hooks:
            count = await hook.cleanup_tag_references(self._db, tag_id_value)
            if count:
                references_removed_by_consumers[hook.consumer_name] = count

        await tag_repository.delete_tag(self._db, tag_id_value)

        return DeleteTagResult(
            tag=tag,
            assignments_removed=assignments_removed,
            references_removed_by_consumers=references_removed_by_consumers,
        )

    # ---------------------------------------------------------------------
    # Assignment
    # ---------------------------------------------------------------------

    async def assign_tag(
        self,
        user: User,
        tag_id: int,
        target_type: str,
        target_id: int,
    ) -> TagAssignment:
        """Assign a tag to a target.

        Global tags require admin access to assign. Private tags are visible
        only to their owner, so only the owner may assign them, and only to a
        target they own. Assignment is idempotent: an existing assignment is
        returned.

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.
            target_type: Type of the target.
            target_id: Primary key of the target.

        Returns:
            The resulting assignment.

        Raises:
            NotFoundError: When the tag or target does not exist.
            ForbiddenError: When the user lacks permission.
            InvalidRequestError: When the target type is unsupported.
            ConflictError: When a concurrent request already created the same
                assignment.
        """
        tag = await tag_repository.get_tag_by_id(self._db, tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist")

        is_global = tag.scope == TagScope.GLOBAL.value
        if is_global:
            self._require_global_scope_admin(user, "assign")
        elif tag.owner_user_id != user.id:
            raise ForbiddenError("You can only assign your own private tags")

        # Validate the polymorphic target exists and, for a private tag, that
        # the user owns it so private vocabulary never crosses users.
        await _validate_target(
            self._db, user, target_type, target_id, enforce_ownership=not is_global
        )

        try:
            await tag_repository.assign_tag(
                self._db, tag_id, target_type, target_id
            )
        except IntegrityError as exc:
            # A concurrent identical assignment won the unique index race.
            raise ConflictError(
                "This tag is already assigned to that target"
            ) from exc
        return await self._get_assignment(tag_id, target_type, target_id)

    async def unassign_tag(
        self,
        user: User,
        tag_id: int,
        target_type: str,
        target_id: int,
    ) -> TagAssignment:
        """Remove an assignment from a target.

        Global tags can be unassigned only by admins. Private tags can be
        unassigned only by their owner.

        Args:
            user: The requesting user.
            tag_id: Primary key of the tag.
            target_type: Type of the target.
            target_id: Primary key of the target.

        Returns:
            The assignment that was removed.

        Raises:
            NotFoundError: When the tag does not exist or no assignment is found.
            ForbiddenError: When the user lacks permission.
            InvalidRequestError: When the target type is unsupported.
        """
        tag = await tag_repository.get_tag_by_id(self._db, tag_id)
        if tag is None:
            raise NotFoundError(f"Tag {tag_id} does not exist")

        if tag.scope == TagScope.GLOBAL.value:
            self._require_global_scope_admin(user, "unassign")
        elif tag.owner_user_id != user.id:
            raise ForbiddenError("You can only unassign your own private tags")

        removed = await tag_repository.unassign_tag(self._db, tag_id, target_type, target_id)
        if removed is None:
            raise NotFoundError(
                f"Tag {tag_id} is not assigned to this {target_type}"
            )

        return removed

    async def _get_assignment(
        self, tag_id: int, target_type: str, target_id: int
    ) -> TagAssignment:
        result = await self._db.execute(
            select(TagAssignment).where(
                TagAssignment.tag_id == tag_id,
                TagAssignment.target_type == target_type,
                TagAssignment.target_id == target_id,
            )
        )
        return result.scalar_one()

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------

    async def near_match_tags(
        self, user: User, normalized_name: str
    ) -> list[Tag]:
        """Return global near matches for a normalized name.

        Args:
            user: The requesting user (unused; globals are public).
            normalized_name: Lowercased, trimmed name.

        Returns:
            List of global near-match tags.
        """
        del user
        return await tag_repository.find_nearly_matching_global_tags(
            self._db,
            normalized_name,
            max_distance=NEAR_MATCH_DISTANCE,
            limit=NEAR_MATCH_LIMIT,
        )

    async def count_assignments(self, tag_id: int) -> int:
        """Return the number of assignments of a tag.

        Args:
            tag_id: Primary key of the tag.

        Returns:
            Assignment count.
        """
        return await tag_repository.count_assignments_for_tag(self._db, tag_id)

    async def count_assignments_by_target_type(
        self, tag_id: int
    ) -> dict[str, int]:
        """Return assignment counts grouped by target type.

        Args:
            tag_id: Primary key of the tag.

        Returns:
            Map from target type to count.
        """
        return await tag_repository.count_assignments_for_tag_by_target_type(
            self._db, tag_id
        )

    async def _now(self) -> datetime:
        """Return the current UTC timestamp for ``updated_at`` writes."""
        return datetime.now(UTC)
