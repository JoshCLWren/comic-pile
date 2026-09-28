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

# Reader capability claims must be backed by a named shipped reader path.
_CAPABILITY_CLAIM_PATTERN = re.compile(
    r"\b(?:you can now|can now|now\s+(?:supports|includes|lets\s+you|handles)"
    r"|(?:is|are)\s+now\s+available)\b",
    re.IGNORECASE,
)
_MIN_USER_VISIBLE_EVIDENCE = 20
_PUBLIC_EVIDENCE_TEXT_LIMITS: dict[str, int] = {
    "classification_reason": 1000,
    "user_visible_evidence": 2000,
    "reader_reachable_path": 500,
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


def _provenance_text(
    provenance: dict[str, object], name: str, *, minimum: int = 1
) -> str:
    """Return a required public-classification provenance string.

    Args:
        provenance: Classification provenance supplied with the release.
        name: Provenance field name being validated.
        minimum: Minimum meaningful character count for the field.

    Returns:
        The stripped provenance text.

    Raises:
        ValueError: If the field is missing, mistyped, empty, too short, or too long.
    """
    value = provenance.get(name)
    if not isinstance(value, str):
        raise ValueError(
            f"provenance_json.{name} must be a string to justify a public release"
        )
    text = value.strip()
    maximum = _PUBLIC_EVIDENCE_TEXT_LIMITS.get(name, 1000)
    if len(text) < minimum:
        raise ValueError(
            f"provenance_json.{name} must describe the change in at least "
            f"{minimum} characters to justify a public release"
        )
    if len(text) > maximum:
        raise ValueError(f"provenance_json.{name} must be at most {maximum} characters")
    return text


def _provenance_string_list(provenance: dict[str, object], name: str) -> list[str]:
    """Return a provenance string-list field, defaulting to an empty list.

    Args:
        provenance: Classification provenance supplied with the release.
        name: Provenance field name being validated.

    Returns:
        The non-empty stripped entries of the list.

    Raises:
        ValueError: If the field is not a list of non-empty strings.
    """
    value = provenance.get(name, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"provenance_json.{name} must be a list of non-empty strings")
    return [item.strip() for item in value]


def _provenance_issue_numbers(provenance: dict[str, object]) -> list[int]:
    """Return the inspected linked issue numbers recorded in provenance.

    Args:
        provenance: Classification provenance supplied with the release.

    Returns:
        Sorted unique positive issue numbers the writer inspected.

    Raises:
        ValueError: If the field is not a list of positive integers.
    """
    value = provenance.get("inspected_issue_numbers", [])
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1
        for item in value
    ):
        raise ValueError(
            "provenance_json.inspected_issue_numbers must be a list of issue numbers"
        )
    return sorted(set(value))


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

    @model_validator(mode="after")
    def require_public_classification_evidence(self) -> Self:
        """Require auditable reader-visible evidence for a public publication.

        Public classification is only accepted when the ledger records why the
        change is reader reachable, which linked issues were inspected, which
        scope fences were found, and what contradicts those fences.

        Args:
            self: Validated release publication request.

        Returns:
            The validated request when public classification evidence is complete.

        Raises:
            ValueError: If classification, reader-reachability, evidence, or
                contradicting-evidence provenance is missing or mistyped.
        """
        if self.status != "published" or self.visibility != "public":
            return self
        provenance = self.provenance_json
        if provenance.get("classification") != "public":
            raise ValueError(
                'provenance_json.classification must be "public" for a public release'
            )
        _provenance_text(provenance, "classification_reason")
        _provenance_text(
            provenance, "user_visible_evidence", minimum=_MIN_USER_VISIBLE_EVIDENCE
        )
        if provenance.get("reader_reachable") is not True:
            raise ValueError(
                "provenance_json.reader_reachable must be true for a public release; "
                "classify the change as internal when no shipped reader path exists"
            )
        _provenance_issue_numbers(provenance)
        scope_fences = _provenance_string_list(provenance, "scope_fences")
        contradicting = _provenance_string_list(provenance, "contradicting_evidence")
        if scope_fences and not contradicting:
            raise ValueError(
                "linked issue scope fences contradict a public release "
                f"({', '.join(scope_fences)}); classify the change as internal or "
                "record provenance_json.contradicting_evidence explaining the "
                "shipped reader path"
            )
        if any(
            _CAPABILITY_CLAIM_PATTERN.search(str(getattr(self, name)))
            for name in _READER_FACING_FIELDS
        ):
            _provenance_text(provenance, "reader_reachable_path")
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
