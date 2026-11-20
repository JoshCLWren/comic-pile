"""Per-resource router mounts for deferred cold-start registration (#3479).

The Vercel function registers only the lightweight ping route
at cold start and completes the rest of the API surface lazily. Importing every
router on the first real request cost 1.5-1.7 s on the measured cold wake, so a
``/api/v1/undo`` tap pulled in catalog and delivery even though the
undo handler never touches them.

This module names one :class:`RouterMount` per router registration unit. Each
mount declares the resource segments it can answer, and
:func:`select_mounts_for_path` maps a concrete request path to the mounts that
must be registered before routing. Registration stays in the historical
``include_router`` order so route precedence is unchanged when several mounts
share a namespace (for example ``/api/v1/threads``).

Declared segments are verified against the eager route table by
``tests/test_cold_start_router_loading.py``: every effective eager route must be
reachable after selecting mounts for its own path, so a new route cannot silently
fall through to the JSON 404 fallback.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import FastAPI

RegisterMount = Callable[[FastAPI], None]

#: Path segments that are registered eagerly and never need deferred loading:
#: ping is mounted by ``app.main`` before this registry is consulted. The
#: former metrics and keepalive eager routers were retired with their Python
#: handlers (served by native Rust v2).
EAGER_SEGMENTS: frozenset[str] = frozenset({"ping"})


@dataclass(frozen=True)
class RouterMount:
    """One deferred router registration unit.

    Attributes:
        key: Stable identifier, also used to de-duplicate registration.
        segments: Resource segments (``threads``, ``undo``, ...) this mount can
            serve. A request whose segment is listed here registers the mount.
        register: Callable that imports and mounts the router(s).
    """

    key: str
    segments: frozenset[str]
    register: RegisterMount


def request_segment(path: str) -> str:
    """Return the resource segment a request path addresses.

    ``/api/v1/undo/`` and ``/api/undo`` both resolve to ``undo``;
    colon-suffixed actions such as ``/api/v1/issues:bulkMarkRead`` resolve to
    their base resource (``issues``). Non-API paths return an empty string.

    Args:
        path: Concrete request path.

    Returns:
        Normalized resource segment, or ``""`` for non-API paths.
    """
    segments = [part for part in path.split("/") if part]
    if segments and segments[0] == "api":
        segments = segments[1:]
    if segments and segments[0] in {"v1", "v2", "v3"}:
        segments = segments[1:]
    if not segments:
        return ""
    return segments[0].split(":", 1)[0]


def select_mounts_for_path(path: str, mounts: Sequence[RouterMount]) -> tuple[RouterMount, ...]:
    """Return the mounts that must be registered to route ``path``.

    Args:
        path: Concrete request path.
        mounts: Candidate mounts, in registration order.

    Returns:
        The matching mounts in registration order; empty when the segment is
        unknown or eager-only, in which case the caller answers from routes that
        are already registered.
    """
    segment = request_segment(path)
    if not segment or segment in EAGER_SEGMENTS:
        return ()
    return tuple(mount for mount in mounts if segment in mount.segments)


def _register_health(app: FastAPI) -> None:
    """Register the bounded warm-up probe."""
    from app.api import health

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])


def _register_threads(app: FastAPI) -> None:
    """Register versioned thread routers; unused bare aliases are retired."""
    from app.api import thread

    app.include_router(thread.router, prefix="/api/v1/threads", tags=["threads"])
    # New client resources (e.g. paginated completed threads for issue #2567)
    # are versioned-only: no bare /api/* twin.
    app.include_router(thread.v1_router, prefix="/api/v1/threads", tags=["threads"])


def _register_issues(app: FastAPI) -> None:
    """Register thread-issue routers (absolute ``/api/v1`` paths)."""
    from app.api import issue

    app.include_router(issue.router, tags=["issues"])


def _register_sessions(app: FastAPI) -> None:
    """Register versioned reading-session routers."""
    from app.api import session

    # Versioned-only new client resources (e.g. the #2744 correction-sheet
    # examples) have no bare /api/* twin. The v1 router is registered before the
    # shared router so its literal paths resolve ahead of /{session_id}.
    app.include_router(session.v1_router, prefix="/api/v1/sessions", tags=["session"])
    app.include_router(session.router, prefix="/api/v1/sessions", tags=["session"])


def _register_dependencies(app: FastAPI) -> None:
    """Register dependency and continuity routers, composing sub-routers first."""
    from app.api import dependency

    # Compose the dependency sub-routers into ``dependency.router`` before the
    # router is copied into the app: ``include_router`` snapshots routes at call
    # time, so sub-routes added afterwards would never be reachable. See
    # ``app.api.dependency.mount_subrouters``.
    dependency.mount_subrouters()
    app.include_router(dependency.router, prefix="/api/v1", tags=["dependencies"])


def _register_catalog(app: FastAPI) -> None:
    """Register catalog series-mapping routers (absolute ``/api/v1`` paths)."""
    from app.api import catalog

    app.include_router(catalog.router, tags=["catalog"])


#: Deferred mounts in historical ``include_router`` order. Segments were derived
#: from the effective eager route table; ``tests/test_cold_start_router_loading.py``
#: fails if a route's segment is missing here.
_CORE_MOUNTS: tuple[RouterMount, ...] = (
    RouterMount("health", frozenset({"health"}), _register_health),
    RouterMount("threads", frozenset({"threads"}), _register_threads),
    RouterMount("issues", frozenset({"issues", "threads"}), _register_issues),
    RouterMount("sessions", frozenset({"sessions"}), _register_sessions),
    RouterMount(
        "dependencies",
        frozenset(
            {
                "continuity-plans",
                "dependencies",
                "issue-identity",
                "issues",
                "reading-order-groups",
                "threads",
            }
        ),
        _register_dependencies,
    ),
    RouterMount("catalog", frozenset({"catalog"}), _register_catalog),
)


def build_router_mounts(environment: str) -> tuple[RouterMount, ...]:
    """Return the deferred mounts for the current environment.

    Args:
        environment: Current application environment string.

    Returns:
        Ordered mounts of production API handlers.
    """
    return _CORE_MOUNTS
