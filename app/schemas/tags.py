"""Pydantic schemas for the tag API.

Request and response models use the fixed palette names from
``app.constants`` and map them to hex values on the wire.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.constants import DEFAULT_TAG_COLOR_NAME


class TagScope(StrEnum):
    """A tag's visibility scope."""

    GLOBAL = "global"
    PRIVATE = "private"


class TagTargetType(StrEnum):
    """A taggable entity type.

    Mirrors ``app.constants.TAG_TARGET_TYPES``; the two must stay in sync.
    """

    ISSUE = "Issue"
    THREAD = "Thread"
    CONTINUITY_PLAN = "ContinuityPlan"


class TagBaseResponse(BaseModel):
    """Shared fields for tag responses."""

    id: int
    name: str
    normalized_name: str
    scope: str
    owner_user_id: int | None
    color: str  # hex ``#RRGGBB`` from the fixed palette
    created_at: datetime
    updated_at: datetime


class TagResponse(TagBaseResponse):
    """A tag response."""


class TagListResponse(BaseModel):
    """List of tags visible to a user."""

    tags: list[TagResponse]


class NearMatchResponse(BaseModel):
    """A global tag that is a near match to a requested name.

    Attributes:
        id: Primary key.
        name: Display name (original casing).
        color: Hex ``#RRGGBB`` value.
        normalized_name: Lowercased name used for matching.
        scope: Always ``"global"``.
    """

    id: int
    name: str
    color: str  # hex ``#RRGGBB``
    normalized_name: str
    scope: str = "global"


class TagCreate(BaseModel):
    """Request to create a tag.

    Attributes:
        name: Raw display name (1-100 characters). Casing is preserved on
            storage and display; the name is lowercased for matching.
        color: Palette name (e.g. ``"red"``) or a hex value matching a palette
            entry. Defaults to ``"red"``.
        scope: ``"global"`` (administrators only) or ``"private"``. Defaults to
            ``"private"``. Non-admin requests for ``"global"`` are refused.
        include_near_matches: When ``True``, the response populates
            ``near_matches`` with global tags whose names are near matches.
            Defaults to ``True`` to suggest similar global tags when creating
            private tags.
    """

    name: str = Field(..., min_length=1, max_length=100)
    color: str = DEFAULT_TAG_COLOR_NAME
    scope: TagScope = TagScope.PRIVATE
    include_near_matches: bool = True


class TagCreateResponse(BaseModel):
    """Response to a tag creation request.

    Attributes:
        tag: The resulting tag. When ``redirected_to_global`` is ``True`` this
            is the existing global tag the request matched.
        redirected_to_global: ``True`` when a private-tag creation request
            matched an existing global tag by normalized name.
        near_matches: Global tags whose names are near matches to the request
            name. Empty unless ``include_near_matches`` was ``True``.
    """

    tag: TagResponse
    redirected_to_global: bool = False
    near_matches: list[NearMatchResponse] = []


class TagUpdate(BaseModel):
    """Request to update a tag.

    Attributes:
        name: New display name. Casing is preserved; name is
            lowercased for matching. Refused if it would collide
            with an existing global tag.
        color: New palette name or hex value. ``None`` leaves the
            color unchanged.
    """

    name: str | None = Field(None, min_length=1, max_length=100)
    color: str | None = None


class TagAssignmentRequest(BaseModel):
    """Request to attach a tag to a target.

    Attributes:
        target_type: One of ``"Issue"``, ``"Thread"``, or ``"ContinuityPlan"``.
        target_id: Primary key of the target row.
    """

    target_type: TagTargetType
    target_id: int = Field(..., gt=0)


class TagAssignmentResponse(BaseModel):
    """A tag assignment.

    Attributes:
        id: Primary key of the assignment.
        tag_id: Referenced tag.
        target_type: Type of the target.
        target_id: Primary key of the target.
        created_at: When the assignment was made.
    """

    id: int
    tag_id: int
    target_type: str
    target_id: int
    created_at: datetime


class TagBulkAssignmentRequest(BaseModel):
    """Request to attach or detach one tag across many targets of one type.

    Bulk operations touch only the requested tag assignment: unrelated tags on
    the selected targets are never replaced or removed.

    Attributes:
        target_type: One of ``"Issue"``, ``"Thread"``, or ``"ContinuityPlan"``.
        target_ids: Primary keys of the target rows. Duplicates are ignored.
    """

    target_type: TagTargetType
    target_ids: list[int] = Field(..., min_length=1, max_length=500)


class TagBulkAssignmentResponse(BaseModel):
    """Result of a bulk tag assignment operation.

    Attributes:
        tag_id: Primary key of the tag.
        target_type: Type of the targets.
        requested_ids: Deduplicated target ids the request asked about.
        affected_ids: Targets whose assignment state actually changed (newly
            assigned for bulk-add, newly removed for bulk-remove).
        already_ids: Targets already in the desired state (already assigned
            for bulk-add, already unassigned for bulk-remove).
        still_inherited_ids: Subset of ``already_ids`` that keep the tag
            through inheritance after a bulk removal (issue #3433). An issue
            whose thread or containing Reading Plan still holds the tag keeps
            showing it even though it has no direct assignment. Always empty
            for bulk adds and for target types that cannot inherit in v1.
    """

    tag_id: int
    target_type: str
    requested_ids: list[int]
    affected_ids: list[int]
    already_ids: list[int]
    still_inherited_ids: list[int] = []


class TagUsageResponse(BaseModel):
    """Assignment usage information for a tag.

    Attributes:
        tag_id: Primary key of the tag.
        total_assignments: Number of ``tag_assignments`` rows for the tag.
        assignments_by_target_type: Assignment counts grouped by target type.
        references_removed_by_consumers: Per-consumer counts of roll-filter or
            other tag references removed during deletion. Empty when no
            consumers are registered.
    """

    tag_id: int
    total_assignments: int
    assignments_by_target_type: dict[str, int]
    references_removed_by_consumers: dict[str, int] = {}


class TagDeleteResponse(BaseModel):
    """Response to a tag deletion.

    Attributes:
        tag_id: Primary key of the deleted tag.
        assignments_removed: Number of ``tag_assignments`` rows deleted.
        references_removed_by_consumers: Per-consumer counts of roll-filter or
            other tag references removed during deletion. Empty when no
            consumers are registered.
    """

    tag_id: int
    assignments_removed: int
    references_removed_by_consumers: dict[str, int] = {}


class InheritanceSourceResponse(BaseModel):
    """One object responsible for an effective tag.

    Attributes:
        target_type: Polymorphic target type (``"Issue"``, ``"Thread"``, or
            ``"ContinuityPlan"``).
        target_id: Primary key of the source object.
        display_name: Human-readable label for navigation (thread title, plan
            name, or issue number).
    """

    target_type: str
    target_id: int
    display_name: str


class EffectiveTagResponse(BaseModel):
    """One deduplicated effective tag with every contributing source.

    Attributes:
        tag: The tag itself.
        direct: ``True`` when the tag is directly assigned to the queried
            object (it may additionally be inherited through parent paths).
        sources: Every object whose direct assignment contributes this tag,
            including the queried object itself for direct assignments. A tag
            inherited through several paths appears once with all of its
            sources retained.
    """

    tag: TagResponse
    direct: bool
    sources: list[InheritanceSourceResponse]


class EffectiveTagsResponse(BaseModel):
    """Direct and effective tags for one object.

    Attributes:
        target_type: Polymorphic target type of the queried object.
        target_id: Primary key of the queried object.
        direct_tags: Tags directly assigned to the object and visible to the
            viewer.
        effective_tags: Union of direct and inherited visible tags,
            deduplicated by tag with all contributing sources retained.
    """

    target_type: str
    target_id: int
    direct_tags: list[TagResponse]
    effective_tags: list[EffectiveTagResponse]


class ThreadIssuesEffectiveTagsResponse(BaseModel):
    """Direct and effective tags for every issue in one thread.

    Bulk read for surfaces that render many issues at once (the thread
    detail issue rows in issue #3422): one response carries each issue's
    effective tags so the client never issues one request per issue.

    Attributes:
        thread_id: Primary key of the thread.
        issues: Per-issue direct and effective tags in canonical position
            order. Issues without any visible tag still appear with empty
            tag lists so clients can distinguish "no tags" from missing
            data without fallback requests.
    """

    thread_id: int
    issues: list[EffectiveTagsResponse]
