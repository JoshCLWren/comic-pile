"""Authentication API endpoints."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
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
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter(tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register_user(
    user_data: UserRegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Register a new user and return tokens.

    Args:
        user_data: User registration data (username, email, password).
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with access and refresh tokens.

    Raises:
        HTTPException: If username or email already exists.
    """
    # Check if username already exists
    result = await db.execute(select(User).where(User.username == user_data.username).limit(1))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email already exists
    if user_data.email:
        result = await db.execute(select(User).where(User.email == user_data.email).limit(1))
        existing_email = result.scalar_one_or_none()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    # Create new user
    hashed_password = hash_password(user_data.password)
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hashed_password,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except sqlalchemy_exc.IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered",
        ) from None

    # Create tokens
    jti = secrets.token_urlsafe(32)
    access_token = create_access_token(data={"sub": user.username, "jti": jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "jti": jti})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
async def login_user(
    login_data: UserLoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate user and return tokens.

    Args:
        login_data: User login data (username, password).
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with access and refresh tokens.

    Raises:
        HTTPException: If credentials are invalid.
    """
    result = await db.execute(select(User).where(User.username == login_data.username).limit(1))
    user = result.scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # Create tokens with JTI for revocation
    jti = secrets.token_urlsafe(32)
    access_token = create_access_token(data={"sub": user.username, "jti": jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "jti": jti})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    refresh_data: RefreshTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Refresh access token using refresh token.

    Args:
        refresh_data: Refresh token request.
        db: SQLAlchemy session for database operations.

    Returns:
        TokenResponse with new access and refresh tokens.

    Raises:
        HTTPException: If refresh token is invalid or revoked.
    """
    try:
        payload = verify_token(refresh_data.refresh_token)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from e
    except (AttributeError, TypeError) as e:
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check if refresh token is revoked
    from app.models.revoked_token import RevokedToken

    result = await db.execute(select(RevokedToken).where(RevokedToken.jti == jti).limit(1))
    revoked = result.scalar_one_or_none()
    if revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    result = await db.execute(select(User).where(User.username == username).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Create new tokens
    new_jti = secrets.token_urlsafe(32)
    access_token = create_access_token(data={"sub": user.username, "jti": new_jti})
    refresh_token = create_refresh_token(data={"sub": user.username, "jti": new_jti})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/logout")
async def logout_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Logout user by revoking their current token.

    Args:
        credentials: HTTP Bearer token credentials.
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with success message.

    Raises:
        HTTPException: If token revocation fails.
    """
    token = credentials.credentials
    try:
        await revoke_token(db, token, current_user.id)
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke token",
        ) from err
    return {"message": "Successfully logged out"}


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
