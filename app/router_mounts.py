"""Per-resource router mounts for deferred cold-start registration (#3479).

The Vercel function registers only the lightweight ping/metrics/keepalive routes
at cold start and completes the rest of the API surface lazily. Importing every
router on the first real request cost 1.5-1.7 s on the measured cold wake, so a
``/api/v1/snooze`` tap pulled in catalog and delivery even though the
snooze handler never touches them.

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

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import FastAPI

RegisterMount = Callable[[FastAPI], None]

#: Path segments that are registered eagerly and never need deferred loading:
#: ping, metrics and keepalive are mounted by ``app.main`` before this registry
#: is consulted.
EAGER_SEGMENTS: frozenset[str] = frozenset({"ping", "metrics", "keepalive"})


@dataclass(frozen=True)
class RouterMount:
    """One deferred router registration unit.

    Attributes:
        key: Stable identifier, also used to de-duplicate registration.
        segments: Resource segments (``threads``, ``snooze``, ...) this mount can
            serve. A request whose segment is listed here registers the mount.
        register: Callable that imports and mounts the router(s).
    """

    key: str
    segments: frozenset[str]
    register: RegisterMount


def request_segment(path: str) -> str:
    """Return the resource segment a request path addresses.

    ``/api/v1/snooze/`` and ``/api/snooze`` both resolve to ``snooze``;
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


def _register_roll(app: FastAPI) -> None:
    """Register roll, roll v1, and roll v2 routers."""
    from app.api import roll

    app.include_router(roll.router, prefix="/api/roll", tags=["roll"])
    app.include_router(roll.router, prefix="/api/v1/roll", tags=["roll"])
    # New client resources (e.g. the Roll exclusion drill-down for #3330) are
    # versioned-only: no bare /api/* twin.
    app.include_router(roll.v1_router, prefix="/api/v1/roll", tags=["roll"])
    # Roll v2: versioned-only, no unversioned alias per #2716
    app.include_router(roll.v2_router, prefix="/api/v2/roll", tags=["roll"])


def _register_admin(app: FastAPI) -> None:
    """Register internal admin routers."""
    from app.api import admin

    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(admin.router, prefix="/api/v1", tags=["admin"])


def _register_analytics(app: FastAPI) -> None:
    """Register analytics routers."""
    from app.api import analytics

    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])


def _register_health(app: FastAPI) -> None:
    """Register bounded health probes."""
    from app.api import health

    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(health.router, prefix="/api/v1", tags=["health"])


def _register_bug_reports(app: FastAPI) -> None:
    """Register bug-report routers."""
    from app.api import bug_report

    app.include_router(bug_report.router, prefix="/api/bug-reports", tags=["bug-reports"])
    app.include_router(bug_report.router, prefix="/api/v1/bug-reports", tags=["bug-reports"])


def _register_auth(app: FastAPI) -> None:
    """Register authentication routers."""
    from app.api import auth

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])


def _register_threads(app: FastAPI) -> None:
    """Register thread routers."""
    from app.api import thread

    app.include_router(thread.router, prefix="/api/threads", tags=["threads"])
    app.include_router(thread.router, prefix="/api/v1/threads", tags=["threads"])
    # New client resources (e.g. paginated completed threads for issue #2567)
    # are versioned-only: no bare /api/* twin.
    app.include_router(thread.v1_router, prefix="/api/v1/threads", tags=["threads"])


def _register_issues(app: FastAPI) -> None:
    """Register thread-issue routers (absolute ``/api/v1`` paths)."""
    from app.api import issue

    app.include_router(issue.router, tags=["issues"])


def _register_comicvine_resolution(app: FastAPI) -> None:
    """Register ComicVine resolution routers (absolute ``/api/v1`` paths)."""
    from app.api import comicvine_resolution

    app.include_router(comicvine_resolution.router, tags=["comicvine-resolution"])


def _register_creators(app: FastAPI) -> None:
    """Register creator routers (absolute ``/api/v1`` paths)."""
    from app.api import creators

    app.include_router(creators.router, tags=["creators"])


def _register_taste(app: FastAPI) -> None:
    """Register taste-discovery routers."""
    from app.api import taste

    app.include_router(taste.router, prefix="/api/v1", tags=["taste"])


def _register_tags(app: FastAPI) -> None:
    """Register tag routers (absolute ``/api/v1`` paths)."""
    from app.api import tags

    app.include_router(tags.router)


def _register_rate(app: FastAPI) -> None:
    """Register rating routers."""
    from app.api import rate

    app.include_router(rate.router, prefix="/api/rate", tags=["rate"])
    app.include_router(rate.router, prefix="/api/v1/rate", tags=["rate"])


def _register_queue(app: FastAPI) -> None:
    """Register queue routers."""
    from app.api import queue

    app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
    app.include_router(queue.router, prefix="/api/v1/queue", tags=["queue"])


def _register_reading_orders(app: FastAPI) -> None:
    """Register reading-order routers (absolute ``/api/v1`` paths)."""
    from app.api import reading_orders

    app.include_router(reading_orders.router, tags=["reading-orders"])


def _register_reading_boundary(app: FastAPI) -> None:
    """Register versioned Reading Boundaries explanation routers."""
    from app.api import reading_boundary

    app.include_router(reading_boundary.router, prefix="/api/v1", tags=["reading-boundaries"])
    app.include_router(reading_boundary.v2_router, prefix="/api/v2", tags=["reading-boundaries-v2"])


def _register_reading_plan_sync(app: FastAPI) -> None:
    """Register reading-plan sync routers."""
    from app.api import reading_plan_sync

    app.include_router(reading_plan_sync.router, prefix="/api/v1", tags=["reading-plan-sync"])


def _register_cron(app: FastAPI) -> None:
    """Register the secret-gated Vercel Cron endpoint."""
    from app.api import cron

    # Machine-triggered Vercel Cron endpoint. It is secret-gated, omitted from
    # the generated client schema, and delegates all work to the sync service.
    app.include_router(cron.router, prefix="/api/v1", tags=["cron"])


def _register_recommendations(app: FastAPI) -> None:
    """Register recommendation diagnostics routers."""
    from app.api import recommendation_diagnostics

    app.include_router(recommendation_diagnostics.router, prefix="/api", tags=["recommendations"])


def _register_sessions(app: FastAPI) -> None:
    """Register session routers."""
    from app.api import session

    app.include_router(session.router, prefix="/api/sessions", tags=["session"])
    # Versioned-only new client resources (e.g. the #2744 correction-sheet
    # examples) have no bare /api/* twin. The v1 router is registered before the
    # legacy twin so its literal paths resolve ahead of /{session_id}.
    app.include_router(session.v1_router, prefix="/api/v1/sessions", tags=["session"])
    app.include_router(session.router, prefix="/api/v1/sessions", tags=["session"])


def _register_reading_mode(app: FastAPI) -> None:
    """Register reading-mode routers (absolute ``/api/v1`` paths)."""
    from app.api import reading_mode

    app.include_router(reading_mode.router, tags=["reading-mode"])


def _register_snooze(app: FastAPI) -> None:
    """Register snooze routers."""
    from app.api import snooze

    app.include_router(snooze.router, prefix="/api/snooze", tags=["snooze"])
    app.include_router(snooze.router, prefix="/api/v1/snooze", tags=["snooze"])


def _register_undo(app: FastAPI) -> None:
    """Register undo routers."""
    from app.api import undo

    app.include_router(undo.router, prefix="/api/undo", tags=["undo"])
    app.include_router(undo.router, prefix="/api/v1/undo", tags=["undo"])


def _register_preferences(app: FastAPI) -> None:
    """Register user-preference routers."""
    from app.api import preferences

    app.include_router(preferences.router, prefix="/api/v1", tags=["users"])


def _register_taste_signals(app: FastAPI) -> None:
    """Register user taste-signal routers."""
    from app.api import taste_signal

    app.include_router(taste_signal.router, prefix="/api/v1", tags=["taste-signals"])


def _register_traffic_metrics(app: FastAPI) -> None:
    """Register traffic-metrics routers."""
    from app.api import traffic_metrics

    app.include_router(traffic_metrics.router, prefix="/api", tags=["traffic"])


def _register_bootstrap_telemetry(app: FastAPI) -> None:
    """Register bootstrap-alias telemetry routers."""
    from app.api import bootstrap_telemetry

    app.include_router(bootstrap_telemetry.router, prefix="/api", tags=["bootstrap-telemetry"])


def _register_dependencies(app: FastAPI) -> None:
    """Register dependency and continuity routers, composing sub-routers first."""
    from app.api import dependency

    # Compose the dependency sub-routers into ``dependency.router`` before the
    # router is copied into the app: ``include_router`` snapshots routes at call
    # time, so sub-routes added afterwards would never be reachable. See
    # ``app.api.dependency.mount_subrouters``.
    dependency.mount_subrouters()
    app.include_router(dependency.router, prefix="/api/v1", tags=["dependencies"])


def _register_delivery(app: FastAPI) -> None:
    """Register delivery routers."""
    from app.api import delivery

    app.include_router(delivery.router, prefix="/api/v1", tags=["delivery"])


def _register_demo(app: FastAPI) -> None:
    """Register the unauthenticated guest demo router."""
    from app.api import demo

    # Guest demo (#2757): versioned-only new client resource, so no bare
    # /api/* twin. It is intentionally unauthenticated and read-only.
    app.include_router(demo.router, prefix="/api/v1/demo", tags=["demo"])


def _register_catalog(app: FastAPI) -> None:
    """Register catalog and external-attach routers (absolute ``/api/v1`` paths)."""
    from app.api import catalog

    app.include_router(catalog.router, tags=["catalog"])


def _register_identity_inbox(app: FastAPI) -> None:
    """Register identity-inbox routers (absolute ``/api/v1`` paths)."""
    from app.api import identity_inbox

    app.include_router(identity_inbox.router, tags=["identity-inbox"])


def _register_issue_identity(app: FastAPI) -> None:
    """Register issue-identity routers (absolute ``/api/v1`` paths)."""
    from app.api import issue_identity

    app.include_router(issue_identity.router, tags=["issue-identity"])


def _register_cbl_adoption(app: FastAPI) -> None:
    """Register CBL adoption-commit routers (absolute ``/api/v1`` paths)."""
    from app.api import cbl_plan_adoption

    app.include_router(cbl_plan_adoption.router, tags=["cbl-adoption-commit"])


def _register_performance_metrics(app: FastAPI) -> None:
    """Register performance-metric collection routers."""
    from app.api import performance_metric

    app.include_router(
        performance_metric.router,
        prefix="/api/v1/performance-metrics",
        tags=["performance-metrics"],
    )



def _register_debug(app: FastAPI) -> None:
    """Register the non-production debug router."""
    from app.api import debug

    app.include_router(debug.router, prefix="/api", tags=["debug"])
    app.include_router(debug.router, prefix="/api/v1", tags=["debug"])


def _register_test_helpers(app: FastAPI) -> None:
    """Register the test-helper router."""
    from app.api.test_helpers import router as test_helpers_router

    app.include_router(test_helpers_router, prefix="/api", tags=["test"])


#: Deferred mounts in historical ``include_router`` order. Segments were derived
#: from the effective eager route table; ``tests/test_cold_start_router_loading.py``
#: fails if a route's segment is missing here.
_CORE_MOUNTS: tuple[RouterMount, ...] = (
    RouterMount("roll", frozenset({"roll"}), _register_roll),
    RouterMount("admin", frozenset({"admin"}), _register_admin),
    RouterMount("analytics", frozenset({"analytics"}), _register_analytics),
    RouterMount("health", frozenset({"health"}), _register_health),
    RouterMount("bug-reports", frozenset({"bug-reports"}), _register_bug_reports),
    RouterMount("auth", frozenset({"auth"}), _register_auth),
    RouterMount("threads", frozenset({"threads"}), _register_threads),
    RouterMount("issues", frozenset({"issues", "threads"}), _register_issues),
    RouterMount(
        "comicvine-resolution",
        frozenset({"comicvine"}),
        _register_comicvine_resolution,
    ),
    RouterMount("creators", frozenset({"creators"}), _register_creators),
    RouterMount("taste", frozenset({"taste"}), _register_taste),
    RouterMount("tags", frozenset({"tags"}), _register_tags),
    RouterMount("rate", frozenset({"rate"}), _register_rate),
    RouterMount("queue", frozenset({"queue"}), _register_queue),
    RouterMount(
        "reading-orders",
        frozenset({"reading-orders", "threads"}),
        _register_reading_orders,
    ),
    RouterMount("reading-boundaries", frozenset({"reading-boundaries"}), _register_reading_boundary),
    RouterMount("reading-plan-sync", frozenset({"reading-plan-sync"}), _register_reading_plan_sync),
    RouterMount("cron", frozenset({"cron"}), _register_cron),
    RouterMount("recommendations", frozenset({"recommendations"}), _register_recommendations),
    RouterMount("sessions", frozenset({"sessions"}), _register_sessions),
    RouterMount("reading-mode", frozenset({"reading-mode"}), _register_reading_mode),
    RouterMount("snooze", frozenset({"snooze"}), _register_snooze),
    RouterMount("undo", frozenset({"undo"}), _register_undo),
    RouterMount("preferences", frozenset({"users"}), _register_preferences),
    RouterMount("taste-signals", frozenset({"users"}), _register_taste_signals),
    RouterMount("traffic-metrics", frozenset({"traffic-metrics"}), _register_traffic_metrics),
    RouterMount(
        "bootstrap-telemetry",
        frozenset({"bootstrap-alias-metrics"}),
        _register_bootstrap_telemetry,
    ),
    RouterMount(
        "dependencies",
        frozenset(
            {
                "collection-exclusions",
                "continuity-plans",
                "continuity-rules",
                "crossover-templates",
                "custom-cbls",
                "dependencies",
                "issue-identity",
                "issues",
                "prerequisites",
                "reading-order-groups",
                "releases",
                # roll_recovery_switch composes under /roll in mount_subrouters().
                "roll",
                "threads",
            }
        ),
        _register_dependencies,
    ),
    RouterMount("delivery", frozenset({"delivery"}), _register_delivery),
    RouterMount("demo", frozenset({"demo"}), _register_demo),
    RouterMount("catalog", frozenset({"catalog", "threads"}), _register_catalog),
    RouterMount("identity-inbox", frozenset({"identity-inbox"}), _register_identity_inbox),
    RouterMount("issue-identity", frozenset({"issue-identity"}), _register_issue_identity),
    RouterMount("cbl-adoption", frozenset({"cbl"}), _register_cbl_adoption),
    RouterMount("performance-metrics", frozenset({"performance-metrics"}), _register_performance_metrics),
)


def build_router_mounts(environment: str) -> tuple[RouterMount, ...]:
    """Return the deferred mounts for the current environment.

    Debug routes exist only outside production and test helpers only when the
    test environment is active, matching the eager registration contract.

    Args:
        environment: Current application environment string.

    Returns:
        Ordered mounts, production-safe debug/test filtering applied.
    """
    mounts = list(_CORE_MOUNTS)
    if environment != "production":
        mounts.append(RouterMount("debug", frozenset({"debug"}), _register_debug))
    if os.getenv("TEST_ENVIRONMENT") == "true":
        mounts.append(RouterMount("test-helpers", frozenset({"test"}), _register_test_helpers))
    return tuple(mounts)
