"""Canonical CBL adoption commit: atomic materialization of reviewed decisions into a Reading Plan.

This module implements the corrective implementation slice for #2127 under #2366.
It takes the exact reviewed CBL adoption preview/decisions from #2126 and
atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

Do NOT persist reader intent into `DependencyGroup` or make `DependencyGroupMembership.sequence_order` a runtime authority.

The endpoint targets one owned Reading Plan and one active CBL source list.
Revalidates the source fingerprint and reviewed entry facts at commit time;
stale preview fails with a structured conflict and no partial writes.

Reuses canonical existing issues. Materializes only explicitly approved
`missing_importable` issues, using stable external series identity and ComicVine
issue identity; fail closed rather than title-guessing.

Preserves existing issue IDs, read status, `read_at`, ratings/events/history,
thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
convergence gates, lanes, name, and ordering mode.

Adds approved source entries to the **same Reading Plan** in reviewed CBL source
order. Existing plan nodes for the same issue are reused, never duplicated.

Persists source provenance on Reading Plan nodes via existing `source_paths` /
`source_cbl_placements` fields.

CBL source position is provenance/order input only. No legacy `cbl-order:source:*`
dependencies and no new `DependencyGroup` reader-state representation.

Does not silently change `informational` to `strict_sequential`. Existing explicit
Reading Plan semantics remain authoritative.

Transactional and idempotent. Concurrent same-user/same-source adoption must
not duplicate issues or Reading Plan nodes.

Returns the updated Reading Plan plus machine-readable reused/created/excluded/
unresolved source positions.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.cbl_adoption import CBLAdoptionCommitRequest
from app.schemas.continuity_plan import ContinuityPlanResponse
from app.services.cbl_plan_adoption import adopt_cbl_material_into_reading_plan

router = APIRouter(tags=["cbl-adoption-commit"])


@router.post(
    "/cbl/{list_id}/adoption-commit",
    response_model=ContinuityPlanResponse,
    status_code=status.HTTP_200_OK,
    description="Atomically commit reviewed CBL adoption material into the existing Reading Plan.",
)
async def api_cbl_adoption_commit(
    list_id: int,
    request: CBLAdoptionCommitRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContinuityPlanResponse:
    """Commit reviewed CBL adoption material into the existing Reading Plan.

    This endpoint implements the corrective implementation slice for #2127 under #2366.
    It takes the exact reviewed CBL adoption preview/decisions from #2126 and
    atomically creates/updates the existing canonical Reading Plan (`ContinuityPlan`).

    The endpoint targets one owned Reading Plan and one active CBL source list.
    Revalidates the source fingerprint and reviewed entry facts at commit time;
    stale preview fails with a structured conflict and no partial writes.

    Reuses canonical existing issues. Materializes only explicitly approved
    `missing_importable` issues, using stable external series identity and ComicVine
    issue identity; fail closed rather than title-guessing.

    Preserves existing issue IDs, read status, `read_at`, ratings/events/history,
    thread identity, existing Reading Plan node IDs, reader overrides, checkpoints,
    convergence gates, lanes, name, and ordering mode.

    Adds approved source entries to the **same Reading Plan** in reviewed CBL source
    order. Existing plan nodes for the same issue are reused, never duplicated.

    Persists source provenance on Reading Plan nodes via existing `source_paths` /
    `source_cbl_placements` fields.

    CBL source position is provenance/order input only. No legacy `cbl-order:source:*`
    dependencies and no new `DependencyGroup` reader-state representation.

    Does not silently change `informational` to `strict_sequential`. Existing explicit
    Reading Plan semantics remain authoritative.

    Transactional and idempotent. Concurrent same-user/same-source adoption must
    not duplicate issues or Reading Plan nodes.

    Returns the updated Reading Plan plus machine-readable reused/created/excluded/
    unresolved source positions.
    """
    plan = await adopt_cbl_material_into_reading_plan(
        db,
        user_id=current_user.id,
        list_id=list_id,
        entry_decisions=request.entry_decisions,
        series_decisions=request.series_decisions,
        series_overrides=request.series_overrides,
    )
    return ContinuityPlanResponse(
        id=plan.id,
        user_id=plan.user_id,
        name=plan.name,
        ordering_mode=plan.ordering_mode,
        lanes=plan.lanes_json,
        nodes=plan.nodes_json,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )