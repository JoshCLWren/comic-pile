"""JWT authentication utilities and dependencies."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_auth_settings
from app.database import get_db
from app.models.user import User
from app.repositories.revoked_token_repository import (
    add_revoked_token,
    get_user_by_username_with_revocation_check,
)

_auth_settings = get_auth_settings()

SECRET_KEY = _auth_settings.secret_key
ALGORITHM = _auth_settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = _auth_settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = _auth_settings.refresh_token_expire_days


def refresh_cookie_max_age_seconds() -> int:
    """Return the HttpOnly refresh cookie lifetime in seconds.

    The cookie must expire with the refresh JWT. A longer cookie would keep a
    dead credential that looks logged-in; a shorter cookie would drop a still-
    valid refresh token.

    Returns:
        Cookie ``max_age`` derived from ``REFRESH_TOKEN_EXPIRE_DAYS``.
    """
    return REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain text password to hash.

    Returns:
        Hashed password string.
    """
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash.

    Args:
        plain_password: Plain text password to verify.
        hashed_password: Hashed password to compare against.

    Returns:
        True if password matches hash, False otherwise.
    """
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create JWT access token.

    Args:
        data: Data to encode in token (e.g., {"sub": username, "jti": token_id}).
        expires_delta: Optional custom expiration time.

    Returns:
        Encoded JWT access token string.
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token.

    Args:
        data: Data to encode in token (e.g., {"sub": username, "jti": token_id}).

    Returns:
        Encoded JWT refresh token string.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify and decode JWT token. Raises JWTError on failure.

    Args:
        token: JWT token string to verify.

    Returns:
        Decoded token payload as dictionary.

    Raises:
        JWTError: If token is invalid or expired.
    """
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    return payload


async def revoke_token(db: AsyncSession, token: str, user_id: int) -> None:
    """Revoke a JWT token by storing its JTI.

    Args:
        db: SQLAlchemy session for database operations.
        token: JWT token to revoke.
        user_id: User ID associated with the token.
    """
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    jti = payload.get("jti")
    if not jti:
        return

    expires_at = datetime.fromtimestamp(payload["exp"], tz=UTC)
    await add_revoked_token(db, user_id=user_id, jti=jti, expires_at=expires_at)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get current authenticated user from JWT token.

    Args:
        credentials: HTTP Bearer token credentials.
        db: SQLAlchemy session for database operations.

    Returns:
        Authenticated User object.

    Raises:
        HTTPException: If token is invalid, expired, or user not found.
    """
    token = credentials.credentials

    try:
        payload = verify_token(token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    except (AttributeError, TypeError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    username = payload.get("sub")
    jti = payload.get("jti")
    token_type = payload.get("type")

    if not username or not isinstance(username, str) or token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not jti or not isinstance(jti, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user, is_revoked = await get_user_by_username_with_revocation_check(
            db, username, jti
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    if is_revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
