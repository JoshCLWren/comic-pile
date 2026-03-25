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
from app.schemas.rate import RateRequest
from app.schemas.roll import OverrideRequest, RollRequest, RollResponse
from app.schemas.session import (
    ActiveThreadInfo,
    EventDetail,
    SessionDetailsResponse,
    SessionListResponse,
    SessionResponse,
)
from app.schemas.snapshot import SnapshotResponse, SnapshotsListResponse
from app.schemas.thread import (
    ReactivateRequest,
    ThreadCreate,
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
    "ThreadListResponse",
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
    # Roll
    "RollRequest",
    "RollResponse",
    "OverrideRequest",
    # Rate
    "RateRequest",
    # Session
    "SessionResponse",
    "SessionListResponse",
    "SessionDetailsResponse",
    "ActiveThreadInfo",
    "EventDetail",
    # Snapshot
    "SnapshotResponse",
    "SnapshotsListResponse",
]
