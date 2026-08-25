"""Authenticated traffic metrics snapshot endpoint.

Serves the process-local per-route request counters used to project cache
command demand against the monthly budget documented in
``docs/CACHE_COMMAND_BUDGET.md``. Aggregates only; no raw paths, query
strings, user identities, or cache keys are exposed.
"""

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.user import User
from app.schemas.traffic_metrics import TrafficMetricsSnapshot
from app.traffic_metrics import traffic_snapshot

router = APIRouter(prefix="/v1", tags=["traffic"])


@router.get("/traffic-metrics", response_model=TrafficMetricsSnapshot)
async def get_traffic_metrics(
    current_user: User = Depends(get_current_user),
) -> TrafficMetricsSnapshot:
    """Return this instance's per-route traffic counters.

    Args:
        current_user: Authenticated user requesting the snapshot.

    Returns:
        Process-local aggregated counters sorted deterministically.
    """
    return traffic_snapshot()
