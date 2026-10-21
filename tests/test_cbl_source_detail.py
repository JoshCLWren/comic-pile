"""Issue #4009: CBL source detail API with complete ordered preview."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread

DETAIL_URL = "/api/v1/issue-identity/cbl-sources"


async def _seed_source(db: AsyncSession) -> CBLSource:
    """Persist one CBL source repository."""
    source = CBLSource(
        repository="example/cbl",
        revision_sha="abc123",
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    return source


async def _seed_list(
    db: AsyncSession,
    *,
    source: CBLSource,
    name: str = "Ultimate Universe",
    path: str = "Marvel/Ultimate.cbl",
    active: bool = True,
    declared_issue_count: int | None = 3,
) -> CBLSourceList:
    """Persist one source list with a schema-valid deterministic content hash."""
    row = CBLSourceList(
        source_id=source.id,
        source_path=path,
        name=name,
        declared_issue_count=declared_issue_count,
        content_hash=sha256(f"{name}|{path}".encode()).hexdigest(),
        revision_sha=source.revision_sha,
        active=active,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_identity(
    db: AsyncSession,
    *,
    external_id: str,
    entity_type: str = "issue",
    provider: str = "comicvine",
) -> ExternalIdentity:
    """Persist one external identity row."""
    identity = ExternalIdentity(
        provider=provider,
        entity_type=entity_type,
        external_id=external_id,
        metadata_json={},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _seed_entry(
    db: AsyncSession,
    *,
    source_list: CBLSourceList,
    position: int,
    series_name: str = "The Avengers",
    issue_number: str = "1",
    volume_year: int | None = 1963,
    publication_year: int | None = 1963,
    issue_identity: ExternalIdentity | None = None,
    series_identity: ExternalIdentity | None = None,
) -> CBLSourceEntry:
    """Persist one ordered source occurrence."""
    entry = CBLSourceEntry(
        list_id=source_list.id,
        position=position,
        series_name=series_name,
        issue_number=issue_number,
        volume_year=volume_year,
        publication_year=publication_year,
        external_issue_identity_id=None if issue_identity is None else issue_identity.id,
        external_series_identity_id=None if series_identity is None else series_identity.id,
    )
    db.add(entry)
    await db.flush()
    return entry


@pytest.mark.asyncio
async def test_detail_returns_ordered_entries_with_comicvine_ids(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Detail returns every occurrence in source order with its Comic Vine IDs."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(async_db, source=source)
    issue_identity = await _seed_identity(async_db, external_id="4000-issue-1")
    series_identity = await _seed_identity(async_db, external_id="2000-volume-1", entity_type="series")

    # Inserted out of order on purpose; the API must return source order.
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=3,
        issue_number="3",
        issue_identity=issue_identity,
        series_identity=series_identity,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_number="1",
        issue_identity=issue_identity,
        series_identity=series_identity,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=2,
        issue_number="2",
        issue_identity=issue_identity,
        series_identity=series_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{DETAIL_URL}/{source_list.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == source_list.id
    assert body["name"] == "Ultimate Universe"
    assert body["source_path"] == "Marvel/Ultimate.cbl"
    assert body["source_repository"] == "example/cbl"
    assert body["source_ref"] == "example/cbl:Marvel/Ultimate.cbl"
    assert body["content_hash"] == source_list.content_hash
    assert body["revision_sha"] == source_list.revision_sha
    assert body["entries_total"] == 3
    assert [entry["position"] for entry in body["entries"]] == [1, 2, 3]
    assert [entry["issue_number"] for entry in body["entries"]] == ["1", "2", "3"]
    assert all(entry["comicvine_issue_id"] == "4000-issue-1" for entry in body["entries"])
    assert all(entry["comicvine_volume_id"] == "2000-volume-1" for entry in body["entries"])
    assert all(entry["series_name"] == "The Avengers" for entry in body["entries"])
    assert all(entry["volume_year"] == 1963 for entry in body["entries"])
    assert all(entry["publication_year"] == 1963 for entry in body["entries"])


@pytest.mark.asyncio
async def test_detail_keeps_repeated_issues_as_separate_occurrences(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A repeated issue stays two ordered occurrences instead of being merged."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(async_db, source=source, declared_issue_count=2)
    issue_identity = await _seed_identity(async_db, external_id="4000-repeated")

    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_number="1",
        issue_identity=issue_identity,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=2,
        issue_number="1",
        issue_identity=issue_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{DETAIL_URL}/{source_list.id}")
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert len(entries) == 2
    assert [entry["position"] for entry in entries] == [1, 2]
    assert [entry["comicvine_issue_id"] for entry in entries] == [
        "4000-repeated",
        "4000-repeated",
    ]


@pytest.mark.asyncio
async def test_detail_reports_missing_and_non_comicvine_identities_as_null(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Missing, wrong-typed, and non-Comic-Vine identities are shown as null."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(async_db, source=source, declared_issue_count=3)
    other_provider = await _seed_identity(
        async_db,
        external_id="other-1",
        entity_type="issue",
        provider="otherprovider",
    )
    wrong_type = await _seed_identity(
        async_db,
        external_id="4000-series-typed-as-issue",
        entity_type="series",
    )

    await _seed_entry(async_db, source_list=source_list, position=1)
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=2,
        issue_identity=other_provider,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=3,
        issue_identity=wrong_type,
    )
    await async_db.commit()

    response = await auth_client.get(f"{DETAIL_URL}/{source_list.id}")
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert [entry["comicvine_issue_id"] for entry in entries] == [None, None, None]
    assert [entry["comicvine_volume_id"] for entry in entries] == [None, None, None]


@pytest.mark.asyncio
async def test_detail_returns_404_for_missing_or_inactive_list(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Missing and inactive source lists are not readable."""
    source = await _seed_source(async_db)
    inactive = await _seed_list(
        async_db,
        source=source,
        name="Archived",
        path="Marvel/Archived.cbl",
        active=False,
    )
    await async_db.commit()

    missing = await auth_client.get(f"{DETAIL_URL}/987654")
    assert missing.status_code == 404, missing.text

    inactive_response = await auth_client.get(f"{DETAIL_URL}/{inactive.id}")
    assert inactive_response.status_code == 404, inactive_response.text


@pytest.mark.asyncio
async def test_detail_pages_large_lists_without_truncation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A large list is returned as bounded pages that cover every occurrence."""
    source = await _seed_source(async_db)
    total = 12
    source_list = await _seed_list(
        async_db,
        source=source,
        declared_issue_count=total,
    )
    for position in range(1, total + 1):
        await _seed_entry(
            async_db,
            source_list=source_list,
            position=position,
            issue_number=str(position),
        )
    await async_db.commit()

    first = await auth_client.get(f"{DETAIL_URL}/{source_list.id}?limit=5")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["entries_total"] == total
    assert first_body["entries_limit"] == 5
    assert first_body["entries_offset"] == 0
    assert [entry["position"] for entry in first_body["entries"]] == [1, 2, 3, 4, 5]

    second = await auth_client.get(f"{DETAIL_URL}/{source_list.id}?limit=5&offset=5")
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["entries_total"] == total
    assert [entry["position"] for entry in second_body["entries"]] == [6, 7, 8, 9, 10]

    third = await auth_client.get(f"{DETAIL_URL}/{source_list.id}?limit=5&offset=10")
    assert third.status_code == 200, third.text
    assert [entry["position"] for entry in third.json()["entries"]] == [11, 12]

    paged_positions = [
        entry["position"]
        for body in (first_body, second_body, third.json())
        for entry in body["entries"]
    ]
    assert paged_positions == list(range(1, total + 1))


@pytest.mark.asyncio
async def test_detail_is_read_only(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The detail preview never creates reader-owned rows."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(async_db, source=source)
    issue_identity = await _seed_identity(async_db, external_id="4000-read-only")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
    )
    await async_db.commit()
    list_id = source_list.id

    async_db.expire_all()
    before = {
        "issues": await async_db.scalar(select(func.count()).select_from(Issue)),
        "threads": await async_db.scalar(select(func.count()).select_from(Thread)),
        "issue_mappings": await async_db.scalar(
            select(func.count()).select_from(IssueExternalIdentityMapping)
        ),
        "series_mappings": await async_db.scalar(
            select(func.count()).select_from(ThreadExternalSeriesMapping)
        ),
        "entries": await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)),
    }

    response = await auth_client.get(f"{DETAIL_URL}/{list_id}")
    assert response.status_code == 200, response.text

    async_db.expire_all()
    after = {
        "issues": await async_db.scalar(select(func.count()).select_from(Issue)),
        "threads": await async_db.scalar(select(func.count()).select_from(Thread)),
        "issue_mappings": await async_db.scalar(
            select(func.count()).select_from(IssueExternalIdentityMapping)
        ),
        "series_mappings": await async_db.scalar(
            select(func.count()).select_from(ThreadExternalSeriesMapping)
        ),
        "entries": await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)),
    }
    assert after == before


@pytest.mark.asyncio
async def test_detail_requires_authentication(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An unauthenticated reader cannot read a CBL source list."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(async_db, source=source)
    await async_db.commit()

    response = await client.get(f"{DETAIL_URL}/{source_list.id}")
    assert response.status_code == 401, response.text
