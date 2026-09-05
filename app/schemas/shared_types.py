"""Shared types for source-backed adoption."""

from enum import StrEnum


class SourceBackedDecision(StrEnum):
    """Decision values for source-backed adoption."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class SourceBackedStatus(StrEnum):
    """Status values for source-backed entries."""

    RESOLVED_VIA_COMICVINE_ID = "resolved_via_comicvine_id"
    RESOLVED_VIA_COMICVINE_CANONICAL = "resolved_via_comicvine_canonical"
    RESOLVED_VIA_TITLE_NUMBER = "resolved_via_title_number"
    NO_OWNED_ISSUE_FOR_COMICVINE_ID = "no_owned_issue_for_comicvine_id"
    AMBIGUOUS_NO_COMICVINE_ID = "ambiguous_no_comicvine_id"
    COMICVINE_IDENTITY_NOT_KNOWN = "comicvine_identity_not_known"
    RESOLVED_VIA_COMICVINE_CANONICAL_AMBIGUOUS = "resolved_via_comicvine_canonical_ambiguous"
