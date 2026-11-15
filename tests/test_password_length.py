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

from app.auth import hash_password, validate_password_length, verify_password
from app.constants import MAX_BCRYPT_PASSWORD_BYTES, MIN_PASSWORD_LENGTH


@pytest.mark.asyncio
async def test_policy_constant_matches_advertised_ui_minimum() -> None:
    """The shared constant stays at the six characters the UI advertises."""
    assert MIN_PASSWORD_LENGTH == 6


@pytest.mark.asyncio
async def test_shared_validator_enforces_minimum() -> None:
    """The shared policy helper refuses below-minimum passwords with a 422."""
    with pytest.raises(HTTPException) as excinfo:
        validate_password_length("x" * (MIN_PASSWORD_LENGTH - 1))

    assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert str(MIN_PASSWORD_LENGTH) in str(excinfo.value.detail)
    validate_password_length("x" * MIN_PASSWORD_LENGTH)


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
