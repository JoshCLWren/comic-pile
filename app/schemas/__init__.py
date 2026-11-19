"""Pydantic schemas for request/response validation.

The package re-exports every public schema so ``from app.schemas import X`` keeps
working, but it resolves each name lazily through a PEP 562 ``__getattr__``
instead of importing every schema module at load time. Eager re-export pulled in
the whole package -- including the heavy recommendation-selection and ORM graph
reached through ``app.schemas.roll`` -- on any request that touched a single
schema, and that dominated the Vercel cold start (issue #3479). The first access
imports only the module that defines the requested name; the import system caches
it from then on, so later accesses are ordinary attribute lookups.

The ``if TYPE_CHECKING`` imports below give static analyzers the real types for
every export; at runtime the module resolves them through ``__getattr__``.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

#: Public export name -> defining module.
_EXPORT_MODULES: dict[str, str] = {
    "AnalyticsMetricsResponse": "app.schemas.analytics",
    "RecentSession": "app.schemas.analytics",
    "TopRatedThread": "app.schemas.analytics",
    "ThreadCreate": "app.schemas.thread",
    "ThreadUpdate": "app.schemas.thread",
    "ThreadResponse": "app.schemas.thread",
    "ThreadDetail": "app.schemas.thread",
    "ThreadListResponse": "app.schemas.thread",
    "ComicVineMappingHealth": "app.schemas.thread",
    "ComicVineMappingStatus": "app.schemas.thread",
    "QueueSeriesMetadata": "app.schemas.thread",
    "QueueThreadListItem": "app.schemas.thread",
    "QueueThreadListResponse": "app.schemas.thread",
    "ReactivateRequest": "app.schemas.thread",
    "PotentialDuplicateMatchType": "app.schemas.thread",
    "PotentialDuplicateMatch": "app.schemas.thread",
    "CheckPotentialDuplicatesRequest": "app.schemas.thread",
    "CheckPotentialDuplicatesResponse": "app.schemas.thread",
    "DependencyResponse": "app.schemas.dependency",
    "BlockingExplanation": "app.schemas.dependency",
    "ThreadDependenciesResponse": "app.schemas.dependency",
    "IssueCreate": "app.schemas.issue",
    "IssueCreatorsEntry": "app.schemas.issue",
    "IssueListResponse": "app.schemas.issue",
    "IssueUpdate": "app.schemas.issue",
    "IssueResponse": "app.schemas.issue",
    "ThreadIssueCreatorsResponse": "app.schemas.issue",
    "KeepaliveResponse": "app.schemas.keepalive",
    "PerformanceMetricCreate": "app.schemas.performance_metric",
    "PerformanceMetricQuery": "app.schemas.performance_metric",
    "PerformanceMetricSummary": "app.schemas.performance_metric",
    "PerformanceMetricComparison": "app.schemas.performance_metric",
    "RollResponse": "app.schemas.roll",
    "RecommendationContextCreate": "app.schemas.recommendation_context",
    "RecommendationContextResponse": "app.schemas.recommendation_context",
    "RollingRecommendationContext": "app.schemas.recommendation_context",
    "SessionResponse": "app.schemas.session",
    "SessionListResponse": "app.schemas.session",
    "SessionListItem": "app.schemas.session",
    "SessionHistoryListResponse": "app.schemas.session",
    "SessionDetailsResponse": "app.schemas.session",
    "ActiveThreadInfo": "app.schemas.session",
    "EventDetail": "app.schemas.session",
    "SessionMode": "app.schemas.session",
    "SessionBandwidthState": "app.schemas.session",
    "SessionIntentState": "app.schemas.session",
    "SnapshotResponse": "app.schemas.snapshot",
    "SnapshotsListResponse": "app.schemas.snapshot",
    "RecommendationDiagnosticsResponse": "app.schemas.recommendation_diagnostics",
    "ControlModeGroup": "app.schemas.recommendation_diagnostics",
    "CoverageInfo": "app.schemas.recommendation_diagnostics",
    "EffortBandOutcome": "app.schemas.recommendation_diagnostics",
}

__all__ = [
    "ActiveThreadInfo",
    "AnalyticsMetricsResponse",
    "BlockingExplanation",
    "CheckPotentialDuplicatesRequest",
    "CheckPotentialDuplicatesResponse",
    "ComicVineMappingHealth",
    "ComicVineMappingStatus",
    "ControlModeGroup",
    "CoverageInfo",
    "DependencyResponse",
    "EffortBandOutcome",
    "EventDetail",
    "IssueCreate",
    "IssueCreatorsEntry",
    "IssueListResponse",
    "IssueResponse",
    "IssueUpdate",
    "KeepaliveResponse",
    "PerformanceMetricComparison",
    "PerformanceMetricCreate",
    "PerformanceMetricQuery",
    "PerformanceMetricSummary",
    "PotentialDuplicateMatch",
    "PotentialDuplicateMatchType",
    "QueueSeriesMetadata",
    "QueueThreadListItem",
    "QueueThreadListResponse",
    "ReactivateRequest",
    "RecentSession",
    "RecommendationContextCreate",
    "RecommendationContextResponse",
    "RecommendationDiagnosticsResponse",
    "RollResponse",
    "RollingRecommendationContext",
    "SessionBandwidthState",
    "SessionDetailsResponse",
    "SessionHistoryListResponse",
    "SessionIntentState",
    "SessionListItem",
    "SessionListResponse",
    "SessionMode",
    "SessionResponse",
    "SnapshotResponse",
    "SnapshotsListResponse",
    "ThreadCreate",
    "ThreadDependenciesResponse",
    "ThreadDetail",
    "ThreadIssueCreatorsResponse",
    "ThreadListResponse",
    "ThreadResponse",
    "ThreadUpdate",
    "TopRatedThread",
]


def __getattr__(name: str) -> object:
    """Resolve a lazily re-exported schema name on first access.

    Args:
        name: Attribute name requested on the package.

    Returns:
        The schema object exported by its defining module.

    Raises:
        AttributeError: If the package does not export ``name``.
    """
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    """Return the declared export surface for ``dir()`` and autocompletion.

    Returns:
        Sorted public export names.
    """
    return sorted(__all__)


if TYPE_CHECKING:
    from app.schemas.analytics import AnalyticsMetricsResponse, RecentSession, TopRatedThread
    from app.schemas.dependency import (
        BlockingExplanation,
        DependencyResponse,
        ThreadDependenciesResponse,
    )
    from app.schemas.issue import (
        IssueCreate,
        IssueListResponse,
        IssueResponse,
        IssueUpdate,
        ThreadIssueCreatorsResponse,
    )
    from app.schemas.keepalive import KeepaliveResponse
    from app.schemas.performance_metric import (
        PerformanceMetricComparison,
        PerformanceMetricCreate,
        PerformanceMetricQuery,
        PerformanceMetricSummary,
    )
    from app.schemas.recommendation_context import (
        RecommendationContextCreate,
        RecommendationContextResponse,
        RollingRecommendationContext,
    )
    from app.schemas.recommendation_diagnostics import (
        ControlModeGroup,
        CoverageInfo,
        EffortBandOutcome,
        RecommendationDiagnosticsResponse,
    )
    from app.schemas.roll import (
        RollResponse,
    )
    from app.schemas.session import (
        ActiveThreadInfo,
        EventDetail,
        SessionBandwidthState,
        SessionDetailsResponse,
        SessionHistoryListResponse,
        SessionIntentState,
        SessionListItem,
        SessionListResponse,
        SessionMode,
        SessionResponse,
    )
    from app.schemas.snapshot import SnapshotResponse, SnapshotsListResponse
    from app.schemas.thread import (
        CheckPotentialDuplicatesRequest,
        CheckPotentialDuplicatesResponse,
        ComicVineMappingHealth,
        ComicVineMappingStatus,
        PotentialDuplicateMatch,
        PotentialDuplicateMatchType,
        QueueSeriesMetadata,
        QueueThreadListItem,
        QueueThreadListResponse,
        ReactivateRequest,
        ThreadCreate,
        ThreadDetail,
        ThreadListResponse,
        ThreadResponse,
        ThreadUpdate,
    )
