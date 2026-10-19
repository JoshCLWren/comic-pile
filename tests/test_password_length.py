"""Server-side password policy tests for issues #3103, #3112, and #3165.

The Register and Reset Password pages advertise a six-character minimum, but
before #3103 only the browser enforced it: the register and reset-password
schemas accepted a one-character password from any direct API client. #3112
closed the remaining gap in the reset-completion service, which hashed and
stored whatever password it was handed even when the request schema was
bypassed. These tests pin the backend to the same advertised policy through
both the public HTTP surface and the service boundary so the rule cannot
silently drift back to UI-only or to a single-path check.

Sign-in is the deliberate exception: ``UserLoginRequest`` is not
minimum-gated so pre-existing short passwords still work, and #3165 removed
the matching client-side minimum from the login form.
"""

import pytest
from fastapi import HTTPException, status
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password, validate_password_length, verify_password
from app.constants import MAX_BCRYPT_PASSWORD_BYTES, MIN_PASSWORD_LENGTH
from app.repositories.user_repository import create_user, get_user_by_username
from app.schemas.auth import ResetPasswordRequest, UserLoginRequest, UserRegisterRequest
from app.services.password_reset_service import complete_reset, request_forgot_password

OLD_PASSWORD = "old-password-long-enough"
RESET_EMAIL = "pwpolicy@example.com"


def _register_payload(password: str, username: str = "pwpolicy") -> dict[str, str]:
    """Build a register request body with the supplied password."""
    return {"username": username, "email": RESET_EMAIL, "password": password}


async def _seed_user_with_reset_token(
    db: AsyncSession, username: str = "pwpolicy-reset"
) -> str:
    """Create a user and mint a live password-reset token for them.

    Returns:
        The raw reset token that ``POST /api/auth/reset-password`` accepts.
    """
    existing = await get_user_by_username(db, username)
    if existing is None:
        await create_user(
            db,
            username=username,
            email=RESET_EMAIL,
            password_hash=hash_password(OLD_PASSWORD),
        )
        await db.commit()
    handoff = await request_forgot_password(db, RESET_EMAIL)
    assert handoff is not None, "reset token handoff should be produced for a known account"
    return handoff.reset_token


@pytest.mark.asyncio
async def test_policy_constant_matches_advertised_ui_minimum() -> None:
    """The shared constant stays at the six characters the UI advertises."""
    assert MIN_PASSWORD_LENGTH == 6


@pytest.mark.asyncio
async def test_register_schema_enforces_minimum() -> None:
    """``UserRegisterRequest`` rejects any password shorter than the minimum."""
    with pytest.raises(ValidationError):
        UserRegisterRequest(
            username="schema",
            email="schema@example.com",
            password="x" * (MIN_PASSWORD_LENGTH - 1),
        )

    request = UserRegisterRequest(
        username="schema",
        email="schema@example.com",
        password="x" * MIN_PASSWORD_LENGTH,
    )
    assert request.password == "x" * MIN_PASSWORD_LENGTH


@pytest.mark.asyncio
async def test_reset_schema_enforces_minimum() -> None:
    """``ResetPasswordRequest`` rejects any new password shorter than the minimum."""
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="tok", new_password="x" * (MIN_PASSWORD_LENGTH - 1))

    request = ResetPasswordRequest(token="tok", new_password="x" * MIN_PASSWORD_LENGTH)
    assert request.new_password == "x" * MIN_PASSWORD_LENGTH


@pytest.mark.asyncio
async def test_login_schema_has_no_minimum() -> None:
    """Sign-in is not minimum-gated so pre-existing short passwords still work."""
    login = UserLoginRequest(username="legacy", password="x")
    assert login.password == "x"


@pytest.mark.asyncio
async def test_shared_validator_enforces_minimum() -> None:
    """The shared policy helper refuses below-minimum passwords with a 422."""
    with pytest.raises(HTTPException) as excinfo:
        validate_password_length("x" * (MIN_PASSWORD_LENGTH - 1))

    assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert str(MIN_PASSWORD_LENGTH) in str(excinfo.value.detail)
    validate_password_length("x" * MIN_PASSWORD_LENGTH)


@pytest.mark.asyncio
async def test_register_rejects_password_below_minimum(client: AsyncClient) -> None:
    """A below-minimum registration is refused by the API, not just the browser."""
    response = await client.post(
        "/api/v1/auth/register", json=_register_payload("1" * (MIN_PASSWORD_LENGTH - 1))
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_register_accepts_password_at_minimum(
    client: AsyncClient, async_db: AsyncSession
) -> None:
    """A password exactly at the minimum registers and is stored hashed."""
    password = "123456"

    response = await client.post("/api/v1/auth/register", json=_register_payload(password))

    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
    user = await get_user_by_username(async_db, "pwpolicy")
    assert user is not None
    assert user.password_hash != password
    assert verify_password(password, user.password_hash)


@pytest.mark.asyncio
async def test_register_accepts_maximum_supported_password(client: AsyncClient) -> None:
    """Passwords up to bcrypt's 72-byte ceiling still register successfully."""
    password = "a" * MAX_BCRYPT_PASSWORD_BYTES

    response = await client.post("/api/v1/auth/register", json=_register_payload(password))

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_reset_rejects_password_below_minimum(
    client: AsyncClient, async_db: AsyncSession
) -> None:
    """A below-minimum reset is refused and leaves the old password in place."""
    token = await _seed_user_with_reset_token(async_db)

    response = await client.post(
        "/api/auth/reset-password",
        json={"token": token, "new_password": "1" * (MIN_PASSWORD_LENGTH - 1)},
    )

    assert response.status_code == 422, response.text
    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    assert verify_password(OLD_PASSWORD, user.password_hash)


@pytest.mark.asyncio
async def test_reset_accepts_password_at_minimum(
    client: AsyncClient, async_db: AsyncSession
) -> None:
    """A reset with a password exactly at the minimum succeeds and rehashes it."""
    token = await _seed_user_with_reset_token(async_db)
    password = "123456"

    response = await client.post(
        "/api/auth/reset-password", json={"token": token, "new_password": password}
    )

    assert response.status_code == 200, response.text
    assert "success" in response.json()["message"].lower()
    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    assert verify_password(password, user.password_hash)


@pytest.mark.asyncio
async def test_reset_service_rejects_password_below_minimum(async_db: AsyncSession) -> None:
    """``complete_reset`` refuses a below-minimum password even without the schema.

    The request schema is not the only caller: an internal caller can invoke the
    service directly, so the minimum must hold at the service boundary too.
    """
    token = await _seed_user_with_reset_token(async_db)
    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    original_hash = user.password_hash

    with pytest.raises(HTTPException) as excinfo:
        await complete_reset(async_db, token, "x" * (MIN_PASSWORD_LENGTH - 1))

    assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    await async_db.refresh(user)
    assert user.password_hash == original_hash
    assert verify_password(OLD_PASSWORD, user.password_hash)
    assert user.password_changed_at is None


@pytest.mark.asyncio
async def test_reset_service_rejection_leaves_token_usable(async_db: AsyncSession) -> None:
    """A refused below-minimum reset never consumes the single-use token."""
    token = await _seed_user_with_reset_token(async_db)

    with pytest.raises(HTTPException):
        await complete_reset(async_db, token, "x" * (MIN_PASSWORD_LENGTH - 1))

    compliant = "correct-horse-battery"
    assert await complete_reset(async_db, token, compliant) is True
    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    assert verify_password(compliant, user.password_hash)


@pytest.mark.asyncio
async def test_reset_service_accepts_password_at_minimum(async_db: AsyncSession) -> None:
    """The service accepts a password exactly at the advertised minimum."""
    token = await _seed_user_with_reset_token(async_db)
    password = "x" * MIN_PASSWORD_LENGTH

    assert await complete_reset(async_db, token, password) is True

    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    assert verify_password(password, user.password_hash)


@pytest.mark.asyncio
async def test_reset_service_rejects_short_password_regardless_of_token(
    async_db: AsyncSession,
) -> None:
    """A below-minimum password is refused as invalid input, not as a bad token.

    The policy check reads only the caller's own input, so the same 422 comes back
    whether or not the reset token exists and it can never act as a signal about
    a live reset link.
    """
    with pytest.raises(HTTPException) as excinfo:
        await complete_reset(async_db, "no-such-token", "x")

    assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid" not in str(excinfo.value.detail)


@pytest.mark.parametrize("password", ["x" * 73, "é" * 37])
async def test_register_rejects_overlong_utf8_password(
    auth_client: AsyncClient, password: str,
) -> None:
    """Oversized ASCII and multibyte input receives validation, never a 500."""
    response = await auth_client.post("/api/v1/auth/register", json=_register_payload(password))
    assert response.status_code == 422
    assert "72 UTF-8 bytes" in response.json()["detail"]


@pytest.mark.parametrize("password", ["x" * 73, "é" * 37])
def test_verify_rejects_overlong_password_without_truncation(password: str) -> None:
    """Login cannot pass oversized input to bcrypt or silently accept a prefix."""
    stored = hash_password("x" * MAX_BCRYPT_PASSWORD_BYTES)
    assert verify_password(password, stored) is False


def test_multibyte_password_at_exact_byte_boundary_is_supported() -> None:
    """The cap counts UTF-8 bytes rather than rejecting valid non-ASCII input."""
    password = "é" * 36
    validate_password_length(password)
    assert verify_password(password, hash_password(password))


async def test_reset_overlong_password_preserves_credentials_and_token(
    async_db: AsyncSession,
) -> None:
    """A refused overlong reset leaves the reader's token usable and hash intact."""
    token = await _seed_user_with_reset_token(async_db)
    with pytest.raises(HTTPException) as error:
        await complete_reset(async_db, token, "é" * 37)
    assert error.value.status_code == 422
    user = await get_user_by_username(async_db, "pwpolicy-reset")
    assert user is not None
    assert verify_password(OLD_PASSWORD, user.password_hash)
    assert await complete_reset(async_db, token, "compliant-replacement-password")


@pytest.mark.parametrize("password", ["x" * 73, "é" * 37])
async def test_login_overlong_password_returns_invalid_credentials(
    auth_client: AsyncClient, async_db: AsyncSession, password: str,
) -> None:
    """An existing account receives a normal 401 instead of a bcrypt exception."""
    await _seed_user_with_reset_token(async_db)
    response = await auth_client.post(
        "/api/v1/auth/login", json={"username": "pwpolicy-reset", "password": password},
    )
    assert response.status_code == 401
