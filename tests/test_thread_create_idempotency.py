"""Idempotent thread creation for double-clicked Create Series (#3466)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thread


def _payload(title: str = "Double Click Series", key: str | None = "key-3466-1") -> dict[str, object]:
    """Build a thread creation payload with an optional idempotency key."""
    payload: dict[str, object] = {
        "title": title,
        "format": "Comic",
        "issues_remaining": 5,
    }
    if key is not None:
        payload["idempotency_key"] = key
    return payload


async def _thread_count(async_db: AsyncSession, title: str) -> int:
    result = await async_db.execute(
        select(func.count()).select_from(Thread).where(Thread.title == title)
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_duplicate_body_key_returns_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Two posts with the same body key create exactly one series."""
    first = await auth_client.post("/api/v1/threads/", json=_payload())
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await auth_client.post("/api/v1/threads/", json=_payload())
    assert second.status_code == 201
    assert second.json()["id"] == first_id

    assert await _thread_count(async_db, "Double Click Series") == 1


@pytest.mark.asyncio
async def test_duplicate_header_key_returns_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The Idempotency-Key header also dedupes a double submit."""
    payload = _payload(title="Header Key Series", key=None)
    headers = {"Idempotency-Key": "key-3466-header"}

    first = await auth_client.post("/api/v1/threads/", json=payload, headers=headers)
    assert first.status_code == 201
    second = await auth_client.post("/api/v1/threads/", json=payload, headers=headers)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert await _thread_count(async_db, "Header Key Series") == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_payload_conflicts(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Reusing a key for a different series is a 409, not a second thread."""
    assert (
        await auth_client.post("/api/v1/threads/", json=_payload(key="key-3466-conflict"))
    ).status_code == 201

    conflict = await auth_client.post(
        "/api/v1/threads/",
        json=_payload(title="Different Series", key="key-3466-conflict"),
    )
    assert conflict.status_code == 409
    assert await _thread_count(async_db, "Different Series") == 0


@pytest.mark.asyncio
async def test_missing_key_keeps_legacy_behavior(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Requests without a key still create independent threads."""
    first = await auth_client.post("/api/v1/threads/", json=_payload(title="Legacy Series", key=None))
    second = await auth_client.post(
        "/api/v1/threads/", json=_payload(title="Legacy Series", key=None)
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert await _thread_count(async_db, "Legacy Series") == 2
