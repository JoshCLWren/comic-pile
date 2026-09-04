"""Pydantic schemas for request/response validation."""

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
    IssueCreate,
    IssueCreateRange,
    IssueListResponse,
    IssueMoveRequest,
    IssueOrderValidationResponse,
    IssueReorderRequest,
    IssueResponse,
    IssueUpdate,
)
from app.schemas.migration import MigrateToIssuesRequest
from app.schemas.preferences import ThemeId, UserPreferencesPatchRequest, UserPreferencesResponse
from app.schemas.rate import RateRequest
from app.schemas.recommendation_explanation import (
    ExplainableFactorResponse,
    RecommendationExplanationResponse,
)
from app.schemas.recommendation_diagnostics import (
    ControlModeGroup,
    CoverageInfo,
    EffortBandOutcome,
    RecommendationDiagnosticsResponse,
)
from app.schemas.roll import (
    OverrideRequest,
    RollBootstrapResponse,
    RollBootstrapThread,
    RollRequest,
    RollResponse,
    SetCurrentIssueRequest,
    SetCurrentIssueResponse,
    SessionModeResponse,
    SessionModeUpdateRequest,
)
from app.schemas.recommendation_context import (
    RecommendationContextCreate,
    RecommendationContextResponse,
    RollingRecommendationContext,
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
from app.schemas.cbl import (
    CBLSourceResponse,
    CBLAdoptionEntryResponse,
    CBLAdoptionSeriesResponse,
    CBLadoptionPlanResponse,
)
from app.schemas.snapshot import SnapshotResponse, SnapshotsListResponse
from app.schemas.thread import (
    QueueThreadListItem,
    QueueThreadListResponse,
    ReactivateRequest,
    ThreadCreate,
    ThreadDetail,
    ThreadListResponse,
    ThreadResponse,
    ThreadUpdate,
)

__all__ = [
    # Auth
    "UserRegisterRequest",
    "UserLoginRequest",
    "TokenResponse",
    "UserResponse",
    "RefreshTokenRequest",
    # Thread
    "ThreadCreate",
    "ThreadUpdate",
    "ThreadResponse",
    "ThreadDetail",
    "ThreadListResponse",
    "QueueThreadListItem",
    "QueueThreadListResponse",
    "ReactivateRequest",
    # Dependency
    "DependencyCreate",
    "DependencyResponse",
    "BlockingExplanation",
    "ThreadDependenciesResponse",
    # Issue
    "IssueCreate",
    "IssueCreateRange",
    "IssueMoveRequest",
    "IssueReorderRequest",
    "IssueUpdate",
    "IssueResponse",
    "IssueListResponse",
    "IssueOrderValidationResponse",
    # Migration
    "MigrateToIssuesRequest",
    # Preferences
    "ThemeId",
    "UserPreferencesResponse",
    "UserPreferencesPatchRequest",
    # Roll
    "RollRequest",
    "RollResponse",
    "OverrideRequest",
    "RollBootstrapThread",
    "RollBootstrapResponse",
    "SetCurrentIssueRequest",
    "SetCurrentIssueResponse",
    "RecommendationExplanationResponse",
    "ExplainableFactorResponse",
    "SessionModeResponse",
    "SessionModeUpdateRequest",
    # Recommendation Context
    "RecommendationContextCreate",
    "RecommendationContextResponse",
    "RollingRecommendationContext",
    # Rate
    "RateRequest",
    # Session
    "SessionResponse",
    "SessionListResponse",
    "SessionListItem",
    "SessionHistoryListResponse",
    "SessionDetailsResponse",
    "ActiveThreadInfo",
    "EventDetail",
    "SessionMode",
    "SessionBandwidthState",
    "SessionIntentState",
    # Snapshot
    "SnapshotResponse",
    "SnapshotsListResponse",
    # Recommendation diagnostics
    "RecommendationDiagnosticsResponse",
    "ControlModeGroup",
    "CoverageInfo",
    "EffortBandOutcome",
]
