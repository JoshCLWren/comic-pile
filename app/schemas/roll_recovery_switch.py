"""Schemas for accepting blocked-roll prerequisite guidance."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RollPrerequisiteSwitchRequest(BaseModel):
    """One recovery recommendation selected from the current Roll guidance."""

    model_config = ConfigDict(extra="forbid")

    node_type: Literal["issue", "crossover"]
    node_id: int


class RollPrerequisiteSwitchResponse(BaseModel):
    """Durable active-target state after accepting a recovery recommendation."""

    original_thread_id: int
    target_thread_id: int
    target_thread_title: str
    target_issue_id: int
    target_issue_number: str
    changed: bool
