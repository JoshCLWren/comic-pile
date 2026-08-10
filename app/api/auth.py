"""Authentication API endpoints."""

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from jose.exceptions import ExpiredSignatureError
from sqlalchemy import exc as sqlalchemy_exc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    hash_password,
    revoke_token,
    verify_password,
    verify_token,
    JWTError,
)
from app.csrf import ensure_csrf_cookie, is_secure_request
from app.database import get_db
from app.middleware import limiter
from app.models.user import User
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from app.security import (
    check_login_lockout,
    clear_failed_logins,
    get_client_ip,
    record_failed_login,
)

router = APIRouter(tags=["auth"])
logger = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api"


def _log_refresh_outcome(request: Request, *, outcome: str, reason: str) -> None:
    """Emit one secret-free structured refresh diagnostic.

    Args:
        request: Incoming refresh request.
        outcome: Stable high-level result, either ``success`` or ``rejected``.
        reason: Stable reason code suitable for production log filtering.
    """
    logger.warning(
        "Auth refresh %s: %s",
        outcome,
        reason,
        extra={
            "event": "auth_refresh",
            "auth_outcome": outcome,
            "auth_reason": reason,
            "path": request.url.path,
            "request_id": getattr(request.state, "request_id", None),
            "level": "WARNING",
        },
    )


def _set_refresh_cookie(response: Response, request: Request, refresh_token: str) -> None:
    """Set refresh token in a secure HttpOnly cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=is_secure_request(request),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=60 * 60 * 24 * 30,
    )


@router.post("/register", response_model=TokenResponse)
async def register_user(
    user_data: UserRegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Register a new user and return tokens.

    Args:
        user_data: User registration data (username, email, password).
        request: Incoming request used for cookie security policy.
        response: Outgoing response used to set auth cookies.
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with access and refresh tokens.

    Raises:
        HTTPException: If username or email already exists.
    """
    conditions = [User.username == user_data.username]
    if user_data.email:
        conditions.append(User.email == user_data.email)

    from sqlalchemy import or_

    result = await db.execute(select(User).where(or_(*conditions)).limit(1))
    existing = result.scalar_one_or_none()
    if existing:
        if existing.username == user_data.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already registered",
            )
        if existing.email == user_data.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    hashed_password = hash_password(user_data.password)
    username = user_data.username
    user = User(
        username=username,
        email=user_data.email,
        password_hash=hashed_password,
    )
    db.add(user)
    try:
        await db.commit()
    except sqlalchemy_exc.IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        ) from None

    jti = secrets.token_urlsafe(32)
    ensure_csrf_cookie(request, response)
    access_token = create_access_token(data={"sub": username, "jti": jti})
    refresh_token = create_refresh_token(data={"sub": username, "jti": jti})
    _set_refresh_cookie(response, request, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login_user(
    login_data: UserLoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate user and return tokens.

    Args:
        login_data: User login data (username, password).
        request: Incoming request used for cookie security policy and IP extraction.
        response: Outgoing response used to set auth cookies.
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with access and refresh tokens.

    Raises:
        HTTPException: If credentials are invalid or account is locked out.
    """
    client_ip = get_client_ip(
        dict(request.headers),
        request.client.host if request.client else None,
    )

    await check_login_lockout(db, username=login_data.username, ip_address=client_ip)

    result = await db.execute(select(User).where(User.username == login_data.username).limit(1))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        await record_failed_login(db, username=login_data.username, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not verify_password(login_data.password, user.password_hash):
        await record_failed_login(db, username=login_data.username, ip_address=client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    await clear_failed_logins(db, username=login_data.username)

    jti = secrets.token_urlsafe(32)
    ensure_csrf_cookie(request, response)
    access_token = create_access_token(data={"sub": user.username, "jti": jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "jti": jti})
    _set_refresh_cookie(response, request, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    refresh_data: RefreshTokenRequest | None = None,
) -> TokenResponse:
    """Refresh access token using refresh token.

    Args:
        request: Incoming request used to read refresh token cookies.
        response: Outgoing response used to rotate refresh cookies.
        refresh_data: Refresh token request.
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with new access and refresh tokens.

    Raises:
        HTTPException: If refresh token is invalid or revoked.
    """
    refresh_token = (
        refresh_data.refresh_token if refresh_data else request.cookies.get(REFRESH_COOKIE_NAME)
    )
    if not refresh_token:
        _log_refresh_outcome(request, outcome="rejected", reason="missing_cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )

    try:
        payload = verify_token(refresh_token)
    except ExpiredSignatureError as e:
        _log_refresh_outcome(request, outcome="rejected", reason="expired_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from e
    except JWTError as e:
        _log_refresh_outcome(request, outcome="rejected", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from e
    except (AttributeError, TypeError) as e:
        _log_refresh_outcome(request, outcome="rejected", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format",
        ) from e

    username = payload.get("sub")
    jti = payload.get("jti")
    token_type = payload.get("type")

    if (
        not username
        or not isinstance(username, str)
        or not jti
        or not isinstance(jti, str)
        or token_type != "refresh"
    ):
        _log_refresh_outcome(request, outcome="rejected", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    from app.models.revoked_token import RevokedToken

    result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti).limit(1))
    revoked = result.scalar_one_or_none()
    if revoked:
        _log_refresh_outcome(request, outcome="rejected", reason="revoked_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    result = await db.execute(select(User).where(User.username == username).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        _log_refresh_outcome(request, outcome="rejected", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    new_jti = secrets.token_urlsafe(32)
    ensure_csrf_cookie(request, response)
    access_token = create_access_token(data={"sub": user.username, "jti": new_jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "jti": new_jti})
    _set_refresh_cookie(response, request, refresh_token)
    _log_refresh_outcome(request, outcome="success", reason="refreshed")

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
async def logout_user(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Logout user by revoking their current token if valid.

    Args:
        request: FastAPI Request object for accessing authorization header.
        response: Response object used to clear auth cookies.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with success message.

    Note:
        This endpoint allows logout even with invalid/expired tokens to enable
        clients to clear local storage and redirect to login.
    """
    auth_header = request.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = verify_token(token)
            username = payload.get("sub")
            if username:
                result = await db.execute(select(User).where(User.username == username).limit(1))
                user = result.scalar_one_or_none()
                if user:
                    await revoke_token(db, token, user.id)
        except (JWTError, AttributeError, TypeError):
            pass

    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=is_secure_request(request),
        samesite="lax",
    )
    return {"message": "Successfully logged out"}


@router.get("/csrf")
async def get_csrf_token(request: Request, response: Response) -> dict[str, str]:
    """Return a CSRF token and ensure the CSRF cookie is present."""
    token = ensure_csrf_cookie(request, response)
    return {"csrf_token": token}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Get current authenticated user's information.

    Args:
        current_user: The authenticated user making the request.

    Returns:
        UserResponse with user details.
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        is_admin=current_user.is_admin,
    )
