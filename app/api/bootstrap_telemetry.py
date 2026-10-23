"""Authenticated bootstrap alias telemetry snapshot endpoint.

Provides process-local alias counters for observability of the
legacy-route deletion gate. No request identity or payload is exposed.
"""

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.user import User
from app.bootstrap_route_telemetry import bootstrap_alias_snapshot
from app.schemas.bootstrap_telemetry import BootstrapAliasCounterSchema, BootstrapAliasSnapshotSchema

router = APIRouter(prefix="/v1", tags=["bootstrap-telemetry"])


@router.get("/bootstrap-alias-metrics", response_model=BootstrapAliasSnapshotSchema)
async def get_bootstrap_alias_metrics(
    current_user: User = Depends(get_current_user),
) -> BootstrapAliasSnapshotSchema:
    """Return this instance's bootstrap alias counters.

    Args:
        current_user: Authenticated user requesting the snapshot.

    Returns:
        Process-local aggregated counters sorted deterministically.
    """
    counters = bootstrap_alias_snapshot()
    schema_counters = [
        BootstrapAliasCounterSchema(
            alias=c.alias,
            web_origin=c.web_origin,
            status_class=c.status_class,
            count=c.count,
        )
        for c in counters
    ]
    return BootstrapAliasSnapshotSchema(counters=schema_counters)
