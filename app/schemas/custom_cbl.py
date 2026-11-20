"""Request and response contracts for user-authored CBL lists."""

from __future__ import annotations

from pydantic import BaseModel


class ReadingListPredecessorChange(BaseModel):
    """Named before/after requirements that the reader must acknowledge."""

    issue_id: int
    issue_name: str
    before_issue_ids: list[int]
    before_issue_names: list[str]
    after_issue_ids: list[int]
    after_issue_names: list[str]
