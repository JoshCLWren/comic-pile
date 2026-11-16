"""Schemas for continuity plan reader operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ContinuityPlanReaderResponse(BaseModel):
    """Option E plan projected from its authoritative Reading List."""

    execution_mode: Literal["option_e"]
    plan_id: int
    name: str
    ordering_mode: Literal["strict_sequential", "informational"]
    progress: dict[str, int]
    available_now: list[dict[str, object]]
    blocked_next: list[dict[str, object]]
    lanes: list[dict[str, object]]
    sources: list[dict[str, object]]
    release_sources: list[dict[str, object]]
    release_candidates: list[dict[str, object]]


class ContinuityPlanRecoveryPreview(BaseModel):
    """Owner-scoped recovery preview for a continuity plan."""

    plan_id: int
    plan_name: str
    plan_updated_at: str
    status: Literal["linked", "orphaned", "ambiguous"]
    linked_list_id: int | None
    retained_steps: list[dict[str, object]]
    candidates: list[dict[str, object]]


class ContinuityPlanRelinkRequest(BaseModel):
    """Request to relink a continuity plan to a Reading List."""

    list_id: int
    expected_plan_updated_at: str
    expected_list_updated_at: str
    confirm: bool


class ContinuityPlanRelinkResult(BaseModel):
    """Result of a continuity plan relink operation."""

    plan_id: int
    list_id: int
    status: Literal["relinked", "already_linked"]