"""Focused regression for #3089 creator filters (role, min_sample, min_average, unread)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_creators_role_filter(auth_client: AsyncClient, db, user, sample_data) -> None:
    """At least writer-filtered results come back with only writer roles."""
    resp = await auth_client.get("/api/v1/creators?role=writer&sort=name")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert "writer" in item["normalized_roles"]


async def test_creators_min_sample_filter(auth_client: AsyncClient, db, user, sample_data) -> None:
    """Minimum sample size filtering returns only creators with enough rated issues."""
    resp = await auth_client.get("/api/v1/creators?min_sample=2")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["ratings_count"] >= 2


async def test_creators_min_average_filter(auth_client: AsyncClient, db, user, sample_data) -> None:
    """Minimum average rating filtering returns only creators meeting the threshold."""
    resp = await auth_client.get("/api/v1/creators?min_average=4.0")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["average_rating"] is not None
        assert item["average_rating"] >= 4.0


async def test_creators_unread_filter_composes(auth_client: AsyncClient, db, user, sample_data) -> None:
    """Unread restriction should not crash and should return a bounded list."""
    resp = await auth_client.get("/api/v1/creators?unread=true")
    assert resp.status_code == 200
    assert "items" in resp.json()
