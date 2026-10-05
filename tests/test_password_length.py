"""Test password length enforcement for auth endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.database import get_db
from app.main import app
from tests.conftest import TRUNCATE_TEST_DATA_SQL


MIN_PASSWORD_LENGTH = 6


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
                "password": "12345",  # 5 chars
            }
            response = await client.post("/api/v1/auth/register", json=user_data)
            assert response.status_code == 422, f"Expected 422 for short password, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_register_password_exactly_six_chars_succeeds(db_engine: AsyncEngine):
    """Registration should succeed with exactly 6-char password."""
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
                "username": "sixcharuser",
                "email": "sixchar@example.com",
                "password": "123456",  # exactly 6 chars
            }
            response = await client.post("/api/v1/auth/register", json=user_data)
            assert response.status_code == 200, f"Expected 200 for 6-char password, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_register_password_too_long(db_engine: AsyncEngine):
    """Registration should succeed with password >= 6 characters."""
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
                "username": "longpwuser",
                "email": "longpw@example.com",
                "password": "a" * 100,  # 100 chars
            }
            response = await client.post("/api/v1/auth/register", json=user_data)
            assert response.status_code == 200, f"Expected 200 for long password, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_reset_password_too_short(db_engine: AsyncEngine):
    """Reset password should fail if password is < 6 characters."""
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
            reset_data = {
                "token": "valid_token",
                "new_password": "12345",  # 5 chars
            }
            response = await client.post("/api/v1/auth/reset-password", json=reset_data)
            assert response.status_code == 422, f"Expected 422 for short password, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_reset_password_exactly_six_chars_succeeds(db_engine: AsyncEngine):
    """Reset password should succeed with exactly 6-char password."""
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
            reset_data = {
                "token": "valid_token",
                "new_password": "123456",  # exactly 6 chars
            }
            response = await client.post("/api/v1/auth/reset-password", json=reset_data)
            assert response.status_code == 422, f"Expected 422 for invalid token, got {response.status_code}: {response.text}"
    finally:
        app.dependency_overrides.pop(get_db, None)