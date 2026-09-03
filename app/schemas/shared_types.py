"""Shared types for source-backed adoption."""

from enum import Enum


class SourceBackedDecision(str, Enum):
    """Decision values for source-backed adoption."""

    INCLUDE = "include"
    EXCLUDE = "exclude"


class SourceBackedStatus(str, Enum):
    """Status values for source-backed entries."""

    EXISTING = "existing"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    DUPLICATE = "duplicate"