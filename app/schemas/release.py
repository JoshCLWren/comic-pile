"""Typed API schemas for the durable release ledger."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReleaseVisibility = Literal["public", "internal"]
ReleaseStatus = Literal["draft", "published", "retracted"]

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?:\/\/[^)]+)\)")
_BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
_MIN_PUBLIC_CONTENT = {"category": 2, "title": 4, "summary": 12}
_READER_FACING_FIELDS = ("category", "title", "summary")

_TICKET_REFERENCE_PATTERN = re.compile(r"(?<![\w&])#\d{1,7}\b")
_SCHEMA_IDENTIFIER_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_PHASE_TERMINOLOGY_PATTERN = re.compile(
    r"\bphases?\s+(?:\d+(?:\.\d+)*|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_UNFINISHED_WORK_PATTERN = re.compile(
    r"\b(?:incomplete|unfinished|todo|wip|not yet implemented)\b",
    re.IGNORECASE,
)

_KNOWN_TYPOS: dict[str, str] = {
    "appearnence": "appearance",
    "appearence": "appearance",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperated": "separated",
    "occured": "occurred",
    "untill": "until",
    "definately": "definitely",
    "accross": "across",
    "existance": "existence",
    "persistant": "persistent",
    "successfull": "successful",
    "compatability": "compatibility",
}


def visible_release_text(value: object) -> str:
    """Return release copy as readers see it after stripping Markdown formatting.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The visible text with link syntax resolved and backticks unwrapped.
    """
    text = _MARKDOWN_LINK_PATTERN.sub(r"\1", str(value))
    return _BACKTICK_PATTERN.sub(r"\1", text)


def find_internal_artifact(field_name: str, value: object) -> str | None:
    """Describe the first internal engineering artifact in reader-facing copy.

    Args:
        field_name: Name of the release field being inspected.
        value: Raw release copy that may hide internal artifacts behind Markdown.

    Returns:
        A human-readable description of the offending fragment, or None when the
        copy reads as ordinary reader-facing product language.
    """
    text = visible_release_text(value)

    def _reason(kind: str, match: re.Match[str]) -> str:
        return f"{field_name} must use reader-facing product language: {kind} '{match.group(0).strip()}'"

    for pattern, kind in (
        (_TICKET_REFERENCE_PATTERN, "internal ticket reference"),
        (_SCHEMA_IDENTIFIER_PATTERN, "database/schema identifier"),
        (_PHASE_TERMINOLOGY_PATTERN, "implementation phase terminology"),
        (_UNFINISHED_WORK_PATTERN, "unfinished-work commentary"),
    ):
        if match := pattern.search(text):
            return _reason(kind, match)

    lowered = text.lower()
    for wrong, right in _KNOWN_TYPOS.items():
        if re.search(rf"\b{wrong}\b", lowered):
            return (
                f"{field_name} must be spell-checked before publication: "
                f"'{wrong}' (did you mean '{right}'?)"
            )
    return None


def _display_length(value: object) -> int:
    """Return the visible length of release copy after stripping Markdown formatting.

    Args:
        value: Raw release copy that may contain Markdown links or backticks.

    Returns:
        The number of visible characters in the stripped text.
    """
    return len(visible_release_text(value).strip())


class ReleaseUpsertRequest(BaseModel):
    """Idempotent release publication payload from trusted automation."""

    source_repository: str = Field(min_length=1, max_length=255)
    source_pr_number: int | None = Field(default=None, ge=1)
    source_merge_sha: str | None = Field(default=None, min_length=7, max_length=64)
    merged_at: datetime | None = None
    released_at: datetime
    category: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1)
    body: str | None = None
    visibility: ReleaseVisibility = "public"
    status: ReleaseStatus = "published"
    sort_order: int = 0
    provenance_json: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_github_identity(self) -> Self:
        """Require at least one stable source identity for retry-safe publication.

        Args:
            self: Validated release publication request.

        Returns:
            The validated request when a GitHub source identity is present.

        Raises:
            ValueError: If both source PR number and merge SHA are absent.
        """
        if self.source_pr_number is None and self.source_merge_sha is None:
            raise ValueError("source_pr_number or source_merge_sha is required")
        return self

    @model_validator(mode="after")
    def enforce_reader_facing_copy(self) -> Self:
        """Reject public published copy that exposes internal engineering artifacts.

        Args:
            self: Validated release publication request.

        Returns:
            The validated request when reader-facing fields carry product language.

        Raises:
            ValueError: If category, title, or summary contains internal ticket
                references, schema identifiers, phase terminology, unfinished-work
                commentary, or a known misspelling.
        """
        if self.status != "published" or self.visibility != "public":
            return self
        for field_name in _READER_FACING_FIELDS:
            artifact = find_internal_artifact(field_name, getattr(self, field_name))
            if artifact is not None:
                raise ValueError(artifact)
        return self

    @model_validator(mode="after")
    def validate_meaningful_content(self) -> Self:
        """Validate that public published releases have meaningful content.

        Args:
            self: Validated release publication request.

        Returns:
            The validated request with meaningful content checks applied.

        Raises:
            ValueError: If public published content is placeholder-sized.
        """
        if self.status != "published" or self.visibility != "public":
            return self
        for field_name, minimum in _MIN_PUBLIC_CONTENT.items():
            if _display_length(getattr(self, field_name)) < minimum:
                raise ValueError(
                    f"{field_name} must contain meaningful release content "
                    f"(at least {minimum} visible characters)"
                )
        return self


class ReleaseResponse(BaseModel):
    """One complete release ledger record returned to trusted automation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_repository: str
    source_pr_number: int | None
    source_merge_sha: str | None
    merged_at: datetime | None
    released_at: datetime
    category: str
    title: str
    summary: str
    body: str | None
    visibility: ReleaseVisibility
    status: ReleaseStatus
    sort_order: int
    provenance_json: dict[str, object]
    created_at: datetime
    updated_at: datetime


class PublicReleaseResponse(BaseModel):
    """One release ledger record returned by public-facing endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    released_at: datetime
    category: str
    title: str
    summary: str
    body: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime


class ReleaseListResponse(BaseModel):
    """Paginated published releases for What's New."""

    releases: list[PublicReleaseResponse]
    total: int
    limit: int
    offset: int


class ReleaseSourceResponse(BaseModel):
    """Result of reconciling a GitHub source identity with the ledger."""

    exists: bool
    release: ReleaseResponse | None = None
