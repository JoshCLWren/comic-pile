"""Canonical Reading Boundary explanation schemas (issues #4024, #4025).

The canonical Option E evaluator decides eligibility. These schemas only
describe that decision for a reader: which Issue can be read next, which live
requirements currently block it, and which reader-owned associations are
historical rather than active.

No schema here exposes a stored blocked flag, a generated adjacency edge, or a
reference-only CBL relationship as an active requirement.
"""

from typing import Literal

from pydantic import BaseModel, Field


class BoundaryReadingList(BaseModel):
    """One owned Reading List that places an Issue."""

    list_id: int
    name: str
    mode: Literal["strict", "loose"]


class BoundaryEditorTarget(BaseModel):
    """Where the reader can change the rule that produced a boundary.

    The target is a descriptor, not a URL: the client owns routing so a
    renamed surface never breaks a stored deep link.
    """

    kind: Literal["reading_list", "prerequisite", "issue"]
    label: str
    list_id: int | None = None
    thread_id: int | None = None
    issue_id: int | None = None
    prerequisite_id: int | None = None


class BoundaryIssue(BaseModel):
    """One named Issue, labeled with its Comic Vine volume when known."""

    issue_id: int
    thread_id: int
    thread_title: str
    issue_number: str
    volume_label: str | None = None
    label: str
    reading_lists: list[BoundaryReadingList] = Field(default_factory=list)


class ReadingBoundaryBlocker(BaseModel):
    """One live Option E requirement that currently blocks the next Issue."""

    kind: Literal["strict_order", "hold", "after_previous", "prerequisite"]
    origin: Literal["reading_list", "reader_prerequisite"]
    reason: str
    waiting_on: list[BoundaryIssue] = Field(default_factory=list)
    editor: BoundaryEditorTarget | None = None


class ReadingBoundaryNext(BaseModel):
    """The Issue the reader may read now."""

    issue: BoundaryIssue
    editor: BoundaryEditorTarget | None = None


class ReadingBoundaryHistorical(BaseModel):
    """A reader-owned association that is not a live blocker.

    Historical rows never gate execution. They are listed so the reader can
    see an old association without it being presented as a live boundary.
    """

    kind: Literal["converted_prerequisite", "legacy_dependency", "skipped_entry"]
    label: str
    detail: str
    editor: BoundaryEditorTarget | None = None


class ReadingBoundaryExplanation(BaseModel):
    """Canonical explanation of one series' reading boundaries."""

    thread_id: int
    state: Literal["blocked", "available", "complete", "unavailable"]
    summary: str
    next: ReadingBoundaryNext | None = None
    blockers: list[ReadingBoundaryBlocker] = Field(default_factory=list)
    historical: list[ReadingBoundaryHistorical] = Field(default_factory=list)


class ReadingBoundaryBatchRequest(BaseModel):
    """Owned series IDs to explain in one request."""

    thread_ids: list[int] = Field(..., min_length=1, max_length=200)


class ReadingBoundaryBatchResponse(BaseModel):
    """Canonical explanations keyed by Thread ID."""

    threads: dict[int, ReadingBoundaryExplanation]