"""Shared types for source-backed adoption."""

from enum import StrEnum


class SourceBackedDecision(StrEnum):
    """Decision values for source-backed adoption."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class SourceBackedStatus(StrEnum):
    """Status values for source-backed entries."""

    EXISTING = "existing"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"
