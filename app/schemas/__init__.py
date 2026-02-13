"""Pydantic schemas for request/response validation."""

from app.schemas.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.schemas.error import (
    ErrorDetail,
    ErrorResponse,
    ErrorResponseWrapper,
    create_error_response,
    http_status_to_name,
)
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
    # Error
    "ErrorDetail",
    "ErrorResponse",
    "ErrorResponseWrapper",
    "create_error_response",
    "http_status_to_name",
    # Thread
    "ThreadCreate",
    "ThreadUpdate",
    "ThreadResponse",
    "ReactivateRequest",
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
