"""Read-only prospective reading-graph preview while adopting a CBL source.

The graph is a projection of the canonical Option E evaluator and cycle
validator. It never writes list membership, issue read state, or overlap
decisions. Every series is identified by its exact Comic Vine volume identity,
so two runs that share a series name never share a decision or a node.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

ReadingGraphChoiceId = Literal["protect_order", "continue_series"]


class ReadingGraphSeriesReference(BaseModel):
    """Exact Comic Vine series/volume identity plus reader-facing labels."""

    comicvine_volume_id: str = Field(min_length=1, max_length=120)
    series_name: str = Field(min_length=1, max_length=500)
    year: int | None = None


class ReadingGraphBlocker(BaseModel):
    """One active unread restriction in the reader's language."""

    kind: Literal["strict_order", "hold", "after_previous", "prerequisite"]
    list_id: int | None = None
    waiting_on_issue_ids: list[int] = Field(default_factory=list)
    gate_issue_id: int | None = None
    explanation: str


class ReadingGraphIssueReference(BaseModel):
    """One concrete comic the prospective graph may name as waiting or rollable."""

    issue_id: int
    series_name: str
    issue_number: str
    comicvine_volume_id: str | None = None
    blockers: list[ReadingGraphBlocker] = Field(default_factory=list)


class ReadingGraphSeriesNode(ReadingGraphSeriesReference):
    """One series node with its prospective eligibility totals."""

    state: Literal["continues", "waits", "mixed"]
    unread_count: int = Field(ge=0)
    rollable_count: int = Field(ge=0)
    waiting_count: int = Field(ge=0)
    waits_for_issue_ids: list[int] = Field(default_factory=list)


class ReadingGraphChoiceEffect(BaseModel):
    """Prospective effect of one answer to a genuine series conflict."""

    choice: ReadingGraphChoiceId
    label: str
    detail: str
    rollable_issue_ids: list[int] = Field(default_factory=list)
    waiting_issue_ids: list[int] = Field(default_factory=list)
    series: list[ReadingGraphSeriesNode] = Field(default_factory=list)


class ReadingGraphOverlap(BaseModel):
    """One conflict between two exact volumes in the prospective list."""

    overlap_id: str = Field(min_length=1, max_length=300)
    continuing_series: ReadingGraphSeriesReference
    waiting_series: ReadingGraphSeriesReference
    question: str
    blocked_issue_ids: list[int] = Field(default_factory=list)
    choices: list[ReadingGraphChoiceEffect] = Field(default_factory=list)
    selected_choice: ReadingGraphChoiceId | None = None


class ReadingGraphCycleError(BaseModel):
    """A cycle or invalid relationship rejected before any write."""

    code: str
    message: str


class ReadingGraphOverlapChoice(BaseModel):
    """One answer the reader has already given during this preview session."""

    overlap_id: str = Field(min_length=1, max_length=300)
    choice: ReadingGraphChoiceId


class ReadingGraphPreviewRequest(BaseModel):
    """Read-only request: included source positions plus answers already given."""

    included_positions: list[Annotated[int, Field(gt=0)]] = Field(
        default_factory=list, max_length=10000
    )
    overlap_choices: list[ReadingGraphOverlapChoice] = Field(default_factory=list, max_length=1000)
    #: Optional existing list to preview as updated rather than newly added.
    target_list_id: Annotated[int | None, Field(gt=0)] = None


class ReadingGraphPreview(BaseModel):
    """Complete read-only graph preview for one source selection."""

    source_list_id: int
    content_hash: str
    revision_sha: str
    series: list[ReadingGraphSeriesNode] = Field(default_factory=list)
    overlaps: list[ReadingGraphOverlap] = Field(default_factory=list)
    issues: list[ReadingGraphIssueReference] = Field(default_factory=list)
    rollable_issue_ids: list[int] = Field(default_factory=list)
    waiting_issue_ids: list[int] = Field(default_factory=list)
    cycle_errors: list[ReadingGraphCycleError] = Field(default_factory=list)
