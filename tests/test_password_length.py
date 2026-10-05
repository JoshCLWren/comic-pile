"""Test password length enforcement for auth endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database import get_db
from app.main import app
from tests.conftest import TRUNCATE_TEST_DATA_SQL

@pytest.mark.asyncio
async def test_register_password_too_short(db_engine: AsyncEngine):
    """Registration should fail if password is < 6 characters."""
    session_maker = async_sessionmaker(bind=db_engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as setup_session:
        await setup_session.execute(TRUNCATE_TEST_DATA_SQL)
        await setup_session.commit()

    async def override():
        async with session_maker() as request_session:
            yield request_session

    app.dependency_overrides[get_db] = override
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            user_data = {
                "username": "shortpwuser",
                "email": "short@example.com",
                "password": "12345", # 5 chars
            }
            response = await client.post("/api/v1/auth/register", json=user_data)
            # Currently this will likely be 200, but we want 422
            assert response.status_code == 422, f"Expected 422 for short password, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)
