"""Pydantic schemas for the tag API.

Request and response models use the fixed palette names from
``app.constants`` and map them to hex values on the wire.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from app.constants import DEFAULT_TAG_COLOR_NAME


class TagScope(str):
    """A tag's visibility scope."""

    GLOBAL = "global"
    PRIVATE = "private"


class TagTargetType(str):
    """A taggable entity type."""

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
    """

    name: str = Field(..., min_length=1, max_length=100)
    color: str = DEFAULT_TAG_COLOR_NAME
    scope: TagScope = TagScope.PRIVATE
    include_near_matches: bool = False


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
