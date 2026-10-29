"""Run the native authentication matrix against the canonical Python dependency."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ALGORITHM, SECRET_KEY, get_current_user
from app.models import User
from app.models.revoked_token import RevokedToken

MATRIX = json.loads(
    (Path(__file__).parent / "fixtures" / "roll-v2" / "auth-matrix.json").read_text()
)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", MATRIX, ids=[case["name"] for case in MATRIX])
async def test_python_native_auth_matrix(db: AsyncSession, case: dict) -> None:
    """Verify the same synthetic claims, revocation and password epochs as Rust."""
    if case.get("missing"):
        # Missing-bearer behavior is covered through HTTP in the existing golden suite.
        from app.auth import security
        from starlette.requests import Request

        request = Request({"type": "http", "headers": []})
        with pytest.raises(HTTPException) as error:
            await security(request)
        assert error.value.status_code == case["status"]
        assert error.value.detail == case["detail"]
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}
        return
    if case["user_exists"]:
        user = User(
            username="reader",
            password_changed_at=datetime.fromtimestamp(case["password_epoch"], UTC),
        )
        db.add(user)
        await db.flush()
        user_id = user.id
        if case["revoked"]:
            db.add(
                RevokedToken(
                    user_id=user_id,
                    jti="test-jti",
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            await db.flush()
    claims = dict(case["claims"])
    claims["exp"] = datetime.now(UTC) + timedelta(
        seconds=-60 if case.get("expired") else 3600
    )
    token = "broken" if case.get("malformed") else jwt.encode(claims, SECRET_KEY, ALGORITHM)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    if case["status"] == 200:
        authenticated = await get_current_user(credentials, db)
        assert authenticated.id == user_id
    else:
        with pytest.raises(HTTPException) as error:
            await get_current_user(credentials, db)
        assert error.value.status_code == case["status"]
        assert error.value.detail == case["detail"]
        assert error.value.headers == {"WWW-Authenticate": "Bearer"}
