"""Issue #2373: Reading Plan Add-material CBL source discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceList


async def _seed_list(
    db: AsyncSession,
    *,
    source: CBLSource,
    name: str,
    path: str,
    active: bool = True,
    count: int | None = 5,
) -> CBLSourceList:
    """Persist one source list with a schema-valid deterministic content hash."""
    row = CBLSourceList(
        source_id=source.id,
        source_path=path,
        name=name,
        declared_issue_count=count,
        content_hash=sha256(f"{name}|{path}".encode()).hexdigest(),
        revision_sha=source.revision_sha,
        active=active,
    )
    db.add(row)
    await db.flush()
    return row


@pytest.mark.asyncio
async def test_discovery_filters_searches_orders_and_limits(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Discovery searches active list metadata in stable bounded order."""
    source = CBLSource(
        repository="example/cbl",
        revision_sha="abc123",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()

    alpha = await _seed_list(
        async_db,
        source=source,
        name="B.P.R.D. Plague of Frogs",
        path="Dark Horse/BPRD/Plague of Frogs.cbl",
    )
    beta = await _seed_list(
        async_db,
        source=source,
        name="B.P.R.D. Hell on Earth",
        path="Dark Horse/BPRD/Hell on Earth.cbl",
    )
    archived = await _seed_list(
        async_db,
        source=source,
        name="Archived B.P.R.D.",
        path="Dark Horse/BPRD/Archived.cbl",
        active=False,
    )
    await _seed_list(
        async_db,
        source=source,
        name="Unrelated Event",
        path="Marvel/Events/Example.cbl",
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/issue-identity/cbl-sources?q=b.p.r.d.")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body] == [beta.id, alpha.id]
    assert all(item["source_repository"] == "example/cbl" for item in body)
    assert archived.id not in {item["id"] for item in body}

    path_match = await auth_client.get(
        "/api/v1/issue-identity/cbl-sources?q=hell%20ON%20earth"
    )
    assert path_match.status_code == 200, path_match.text
    assert [item["id"] for item in path_match.json()] == [beta.id]

    limited = await auth_client.get("/api/v1/issue-identity/cbl-sources?limit=1")
    assert limited.status_code == 200, limited.text
    assert len(limited.json()) == 1

    missing = await auth_client.get("/api/v1/issue-identity/cbl-sources?q=no-such-list")
    assert missing.status_code == 200, missing.text
    assert missing.json() == []


@pytest.mark.asyncio
async def test_discovery_is_read_only(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Discovery leaves persisted source and source-list row counts unchanged."""
    source = CBLSource(
        repository="example/read-only",
        revision_sha="def456",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    await _seed_list(
        async_db,
        source=source,
        name="B.P.R.D. Omnibus",
        path="Dark Horse/BPRD/Omnibus.cbl",
    )
    await async_db.commit()

    before_sources = await async_db.scalar(select(func.count()).select_from(CBLSource))
    before_lists = await async_db.scalar(select(func.count()).select_from(CBLSourceList))

    response = await auth_client.get("/api/v1/issue-identity/cbl-sources?q=BPRD")
    assert response.status_code == 200, response.text

    async_db.expire_all()
    after_sources = await async_db.scalar(select(func.count()).select_from(CBLSource))
    after_lists = await async_db.scalar(select(func.count()).select_from(CBLSourceList))
    assert after_sources == before_sources
    assert after_lists == before_lists
