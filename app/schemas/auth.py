"""Auth schemas for request/response validation."""

from typing import Annotated

from pydantic import AliasChoices, BaseModel, EmailStr, Field, StringConstraints


class UserRegisterRequest(BaseModel):
    """Request schema for user registration."""

    username: str
    email: EmailStr
    password: str


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    identifier: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1),
        Field(
            description="Your username or email address.",
            validation_alias=AliasChoices("identifier", "username"),
        ),
    ]
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
