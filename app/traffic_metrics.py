"""Process-local per-route request counting for cache and capacity planning.

Counters are keyed by HTTP method, routed path template (for example
``/api/v1/threads/{thread_id}``), and response status class. Raw paths,
query strings, user identities, and cache keys are never recorded, so the
aggregates are safe to expose to authenticated users.

Vercel deploys this application as ephemeral serverless instances, so these
counters only cover the lifetime of one process. A collector reconstructs
fleet-wide totals by keeping the maximum count per key across polls of the
same instance ID; counters are monotonic within a process lifetime.
"""

import secrets
import threading
from collections.abc import Mapping
from typing import Final

from app.schemas.traffic_metrics import RouteTrafficCounter, TrafficMetricsSnapshot

_UNMATCHED_ROUTE: Final = "__unmatched__"
_OVERFLOW_ROUTE: Final = "__overflow__"
_MAX_TRACKED_KEYS: Final = 500

_instance_id: Final[str] = f"traffic-{secrets.token_urlsafe(8)}"
_lock: Final = threading.Lock()
_counts: dict[tuple[str, str, str], int] = {}


def get_traffic_instance_id() -> str:
    """Return the stable process-scoped identifier for this instance.

    Returns:
        A short random identifier assigned once at module import.
    """
    return _instance_id


def reset_traffic_counters_for_tests() -> None:
    """Clear every counter. Intended for test isolation only."""
    with _lock:
        _counts.clear()


def resolve_route_template(scope: Mapping[str, object]) -> str:
    """Resolve the routed path template from a request scope.

    FastAPI stores the matched route on the request scope while the endpoint
    runs, so calling this after routing resolves yields a cardinality-safe
    template such as ``/api/v1/threads/{thread_id}``.

    Args:
        scope: The ASGI request scope dictionary.

    Returns:
        The route path template, or ``__unmatched__`` when no route matched.
    """
    route = scope.get("route")
    path_template = getattr(route, "path", None)
    if isinstance(path_template, str) and path_template:
        return path_template
    return _UNMATCHED_ROUTE


def record_route_hit(method: str, path_template: str, status_code: int) -> None:
    """Record one completed request against its route template.

    Args:
        method: HTTP method of the request.
        path_template: Routed path template from :func:`resolve_route_template`.
        status_code: Response status code returned to the client.
    """
    status_class = f"{status_code // 100}xx"
    key = (method.upper(), path_template, status_class)
    with _lock:
        if key in _counts or len(_counts) < _MAX_TRACKED_KEYS:
            _counts[key] = _counts.get(key, 0) + 1
            return
        overflow_key = (key[0], _OVERFLOW_ROUTE, key[2])
        _counts[overflow_key] = _counts.get(overflow_key, 0) + 1


def traffic_snapshot() -> TrafficMetricsSnapshot:
    """Return the current process-local traffic tally.

    Returns:
        Snapshot with ``instance_id`` and a deterministically sorted
        ``counters`` list of aggregated request tallies.
    """
    with _lock:
        counters = [
            RouteTrafficCounter(
                method=method,
                route=route,
                status_class=status_class,
                count=count,
            )
            for (method, route, status_class), count in sorted(_counts.items())
        ]
    return TrafficMetricsSnapshot(instance_id=_instance_id, counters=counters)
