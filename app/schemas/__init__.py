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
    "UserRegisterRequest": "app.schemas.auth",
    "UserLoginRequest": "app.schemas.auth",
    "TokenResponse": "app.schemas.auth",
    "UserResponse": "app.schemas.auth",
    "RefreshTokenRequest": "app.schemas.auth",
    "ThreadCreate": "app.schemas.thread",
    "ThreadUpdate": "app.schemas.thread",
    "ThreadResponse": "app.schemas.thread",
    "ThreadDetail": "app.schemas.thread",
    "ThreadListResponse": "app.schemas.thread",
    "ComicVineMappingHealth": "app.schemas.thread",
    "ComicVineMappingStatus": "app.schemas.thread",
    "QueueThreadListItem": "app.schemas.thread",
    "QueueThreadListResponse": "app.schemas.thread",
    "ReactivateRequest": "app.schemas.thread",
    "DependencyCreate": "app.schemas.dependency",
    "DependencyResponse": "app.schemas.dependency",
    "BlockingExplanation": "app.schemas.dependency",
    "ThreadDependenciesResponse": "app.schemas.dependency",
    "IssueBulkMarkReadRequest": "app.schemas.issue",
    "IssueBulkMarkUnreadRequest": "app.schemas.issue",
    "IssueCreate": "app.schemas.issue",
    "IssueCreateRange": "app.schemas.issue",
    "IssueMoveRequest": "app.schemas.issue",
    "IssueReorderRequest": "app.schemas.issue",
    "IssueUpdate": "app.schemas.issue",
    "IssueResponse": "app.schemas.issue",
    "IssueListResponse": "app.schemas.issue",
    "IssueCreatorsEntry": "app.schemas.issue",
    "ThreadIssueCreatorsResponse": "app.schemas.issue",
    "IssueOrderValidationResponse": "app.schemas.issue",
    "MigrateToIssuesRequest": "app.schemas.migration",
    "KeepaliveResponse": "app.schemas.keepalive",
    "PerformanceMetricCreate": "app.schemas.performance_metric",
    "PerformanceMetricQuery": "app.schemas.performance_metric",
    "PerformanceMetricSummary": "app.schemas.performance_metric",
    "PerformanceMetricComparison": "app.schemas.performance_metric",
    "ThemeId": "app.schemas.preferences",
    "UserPreferencesResponse": "app.schemas.preferences",
    "UserPreferencesPatchRequest": "app.schemas.preferences",
    "RollRequest": "app.schemas.roll",
    "RollResponse": "app.schemas.roll",
    "OverrideRequest": "app.schemas.roll",
    "RollBootstrapThread": "app.schemas.roll",
    "RollBootstrapResponse": "app.schemas.roll",
    "RollExclusionPageResponse": "app.schemas.roll",
    "ThreadExclusionReason": "app.schemas.roll",
    "SetCurrentIssueRequest": "app.schemas.roll",
    "SetCurrentIssueResponse": "app.schemas.roll",
    "RecommendationExplanationResponse": "app.schemas.recommendation_explanation",
    "ExplainableFactorResponse": "app.schemas.recommendation_explanation",
    "SessionModeResponse": "app.schemas.roll",
    "SessionModeUpdateRequest": "app.schemas.roll",
    "RecommendationContextCreate": "app.schemas.recommendation_context",
    "RecommendationContextResponse": "app.schemas.recommendation_context",
    "RollingRecommendationContext": "app.schemas.recommendation_context",
    "RateRequest": "app.schemas.rate",
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
    "CorrectionChoiceId": "app.schemas.session",
    "CorrectionSheetExamplesResponse": "app.schemas.session",
    "SnapshotResponse": "app.schemas.snapshot",
    "SnapshotsListResponse": "app.schemas.snapshot",
    "RecommendationDiagnosticsResponse": "app.schemas.recommendation_diagnostics",
    "ControlModeGroup": "app.schemas.recommendation_diagnostics",
    "CoverageInfo": "app.schemas.recommendation_diagnostics",
    "EffortBandOutcome": "app.schemas.recommendation_diagnostics",
    "CheckPotentialDuplicatesRequest": "app.schemas.thread",
    "CheckPotentialDuplicatesResponse": "app.schemas.thread",
    "PotentialDuplicateMatch": "app.schemas.thread",
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
    "CorrectionChoiceId",
    "CorrectionSheetExamplesResponse",
    "CoverageInfo",
    "DependencyCreate",
    "DependencyResponse",
    "EffortBandOutcome",
    "EventDetail",
    "ExplainableFactorResponse",
    "IssueBulkMarkReadRequest",
    "IssueBulkMarkUnreadRequest",
    "IssueCreate",
    "IssueCreateRange",
    "IssueCreatorsEntry",
    "IssueListResponse",
    "IssueMoveRequest",
    "IssueOrderValidationResponse",
    "IssueReorderRequest",
    "IssueResponse",
    "IssueUpdate",
    "KeepaliveResponse",
    "MigrateToIssuesRequest",
    "OverrideRequest",
    "PerformanceMetricComparison",
    "PerformanceMetricCreate",
    "PerformanceMetricQuery",
    "PerformanceMetricSummary",
    "PotentialDuplicateMatch",
    "QueueThreadListItem",
    "QueueThreadListResponse",
    "RateRequest",
    "ReactivateRequest",
    "RecentSession",
    "RecommendationContextCreate",
    "RecommendationContextResponse",
    "RecommendationDiagnosticsResponse",
    "RecommendationExplanationResponse",
    "RefreshTokenRequest",
    "RollBootstrapResponse",
    "RollBootstrapThread",
    "RollExclusionPageResponse",
    "RollRequest",
    "RollResponse",
    "RollingRecommendationContext",
    "SessionBandwidthState",
    "SessionDetailsResponse",
    "SessionHistoryListResponse",
    "SessionIntentState",
    "SessionListItem",
    "SessionListResponse",
    "SessionMode",
    "SessionModeResponse",
    "SessionModeUpdateRequest",
    "SessionResponse",
    "SetCurrentIssueRequest",
    "SetCurrentIssueResponse",
    "SnapshotResponse",
    "SnapshotsListResponse",
    "ThemeId",
    "ThreadCreate",
    "ThreadDependenciesResponse",
    "ThreadDetail",
    "ThreadExclusionReason",
    "ThreadIssueCreatorsResponse",
    "ThreadListResponse",
    "ThreadResponse",
    "ThreadUpdate",
    "TokenResponse",
    "TopRatedThread",
    "UserLoginRequest",
    "UserPreferencesPatchRequest",
    "UserPreferencesResponse",
    "UserRegisterRequest",
    "UserResponse",
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
    from app.schemas.auth import (
        RefreshTokenRequest,
        TokenResponse,
        UserLoginRequest,
        UserRegisterRequest,
        UserResponse,
    )
    from app.schemas.dependency import (
        BlockingExplanation,
        DependencyCreate,
        DependencyResponse,
        ThreadDependenciesResponse,
    )
    from app.schemas.issue import (
        IssueBulkMarkReadRequest,
        IssueBulkMarkUnreadRequest,
        IssueCreate,
        IssueCreateRange,
        IssueCreatorsEntry,
        IssueListResponse,
        IssueMoveRequest,
        IssueOrderValidationResponse,
        IssueReorderRequest,
        IssueResponse,
        IssueUpdate,
        ThreadIssueCreatorsResponse,
    )
    from app.schemas.keepalive import KeepaliveResponse
    from app.schemas.migration import MigrateToIssuesRequest
    from app.schemas.performance_metric import (
        PerformanceMetricComparison,
        PerformanceMetricCreate,
        PerformanceMetricQuery,
        PerformanceMetricSummary,
    )
    from app.schemas.preferences import (
        ThemeId,
        UserPreferencesPatchRequest,
        UserPreferencesResponse,
    )
    from app.schemas.rate import RateRequest
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
    from app.schemas.recommendation_explanation import (
        ExplainableFactorResponse,
        RecommendationExplanationResponse,
    )
    from app.schemas.roll import (
        OverrideRequest,
        RollBootstrapResponse,
        RollBootstrapThread,
        RollExclusionPageResponse,
        RollRequest,
        RollResponse,
        SessionModeResponse,
        SessionModeUpdateRequest,
        SetCurrentIssueRequest,
        SetCurrentIssueResponse,
        ThreadExclusionReason,
    )
    from app.schemas.session import (
        ActiveThreadInfo,
        CorrectionChoiceId,
        CorrectionSheetExamplesResponse,
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
        QueueThreadListItem,
        QueueThreadListResponse,
        ReactivateRequest,
        ThreadCreate,
        ThreadDetail,
        ThreadListResponse,
        ThreadResponse,
        ThreadUpdate,
    )
