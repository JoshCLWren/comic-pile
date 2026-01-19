"""Auth schemas for request/response validation."""

from pydantic import BaseModel, EmailStr


class UserRegisterRequest(BaseModel):
    """Request schema for user registration."""

    username: str
    email: EmailStr
    password: str


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Response schema for token endpoints."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Response schema for user information."""

    id: int
    username: str
    email: str | None
    is_admin: bool


class RefreshTokenRequest(BaseModel):
    """Request schema for token refresh."""

    refresh_token: str
