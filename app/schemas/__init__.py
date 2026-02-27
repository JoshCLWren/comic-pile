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
    IssueResponse,
    IssueUpdate,
)
from app.schemas.migration import MigrateToIssuesRequest
from app.schemas.rate import RateRequest
from app.schemas.roll import OverrideRequest, RollResponse
from app.schemas.session import (
    ActiveThreadInfo,
    EventDetail,
    SessionDetailsResponse,
    SessionResponse,
)
from app.schemas.snapshot import SnapshotResponse, SnapshotsListResponse
from app.schemas.thread import (
    ReactivateRequest,
    ThreadCreate,
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
    "ReactivateRequest",
    # Dependency
    "DependencyCreate",
    "DependencyResponse",
    "BlockingExplanation",
    "ThreadDependenciesResponse",
    # Issue
    "IssueCreate",
    "IssueCreateRange",
    "IssueUpdate",
    "IssueResponse",
    "IssueListResponse",
    # Migration
    "MigrateToIssuesRequest",
    # Roll
    "RollResponse",
    "OverrideRequest",
    # Rate
    "RateRequest",
    # Session
    "SessionResponse",
    "SessionDetailsResponse",
    "ActiveThreadInfo",
    "EventDetail",
    # Snapshot
    "SnapshotResponse",
    "SnapshotsListResponse",
]
