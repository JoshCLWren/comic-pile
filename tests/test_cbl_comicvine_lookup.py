"""Issue #4011: CBL reverse lookup by exact Comic Vine issue identity."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User

LOOKUP_URL = "/api/v1/issue-identity/cbl-sources/by-comicvine-issue"


async def _seed_source(
    db: AsyncSession,
    *,
    repository: str = "example/cbl",
    revision_sha: str = "abc123",
) -> CBLSource:
    """Persist one CBL source repository."""
    source = CBLSource(
        repository=repository,
        revision_sha=revision_sha,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    return source


async def _seed_list(
    db: AsyncSession,
    *,
    source: CBLSource,
    name: str,
    path: str,
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
    series_name: str = "Mister Miracle",
    issue_number: str = "1",
    volume_year: int | None = 1985,
    publication_year: int | None = 1985,
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
async def test_lookup_returns_every_occurrence_across_lists(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An unowned Comic Vine ID returns all three occurrences in two lists."""
    source = await _seed_source(async_db)
    alpha = await _seed_list(
        async_db,
        source=source,
        name="Alpha Reading",
        path="Marvel/Alpha.cbl",
    )
    beta = await _seed_list(
        async_db,
        source=source,
        name="Beta Reading",
        path="Marvel/Beta.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-issue-1")
    volume_identity = await _seed_identity(
        async_db, external_id="2000-volume-1", entity_type="series"
    )

    await _seed_entry(
        async_db,
        source_list=alpha,
        position=1,
        issue_identity=issue_identity,
        series_identity=volume_identity,
    )
    await _seed_entry(
        async_db,
        source_list=alpha,
        position=4,
        issue_identity=issue_identity,
        series_identity=volume_identity,
    )
    await _seed_entry(
        async_db,
        source_list=beta,
        position=2,
        issue_identity=issue_identity,
        series_identity=volume_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-issue-1")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["comicvine_issue_id"] == "4000-issue-1"
    assert body["occurrences_total"] == 3
    assert body["lists_total"] == 2
    assert len(body["occurrences"]) == 3

    occurrences = body["occurrences"]
    assert all(item["comicvine_issue_id"] == "4000-issue-1" for item in occurrences)
    assert all(item["comicvine_volume_id"] == "2000-volume-1" for item in occurrences)
    assert all(item["series_name"] == "Mister Miracle" for item in occurrences)

    by_list: dict[int, list[int]] = {}
    for item in occurrences:
        by_list.setdefault(item["list_id"], []).append(item["position"])
    assert by_list == {alpha.id: [1, 4], beta.id: [2]}

    names = {item["list_id"]: item["list_name"] for item in occurrences}
    assert names == {alpha.id: "Alpha Reading", beta.id: "Beta Reading"}
    assert {item["source_path"] for item in occurrences} == {
        "Marvel/Alpha.cbl",
        "Marvel/Beta.cbl",
    }
    assert {item["source_repository"] for item in occurrences} == {"example/cbl"}
    assert {item["source_ref"] for item in occurrences} == {
        "example/cbl:Marvel/Alpha.cbl",
        "example/cbl:Marvel/Beta.cbl",
    }


@pytest.mark.asyncio
async def test_lookup_does_not_match_by_title_or_by_other_issue_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Same title or same volume never produces a false positive."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Mister Miracle",
        path="Marvel/Mister Miracle.cbl",
    )
    target_identity = await _seed_identity(async_db, external_id="4000-target")
    other_identity = await _seed_identity(async_db, external_id="4000-other")
    volume_identity = await _seed_identity(
        async_db, external_id="2000-volume-1", entity_type="series"
    )

    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        series_name="Mister Miracle",
        issue_number="1",
        issue_identity=target_identity,
        series_identity=volume_identity,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=2,
        series_name="Mister Miracle",
        issue_number="1",
        issue_identity=other_identity,
        series_identity=volume_identity,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=3,
        series_name="Mister Miracle",
        issue_number="2",
        issue_identity=other_identity,
        series_identity=volume_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-target")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["occurrences_total"] == 1
    assert body["lists_total"] == 1
    assert [item["position"] for item in body["occurrences"]] == [1]
    assert body["occurrences"][0]["comicvine_issue_id"] == "4000-target"


@pytest.mark.asyncio
async def test_lookup_reports_volume_context_and_tolerates_missing_series_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Volume identity is reported as context and stays null when unknown."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Volume Context",
        path="Marvel/Context.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-context")
    comicvine_volume = await _seed_identity(
        async_db, external_id="2000-volume-comicvine", entity_type="series"
    )
    other_provider_volume = await _seed_identity(
        async_db,
        external_id="other-volume-1",
        entity_type="series",
        provider="otherprovider",
    )

    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
        series_identity=comicvine_volume,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=2,
        issue_identity=issue_identity,
        series_identity=other_provider_volume,
    )
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=3,
        issue_identity=issue_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-context")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["occurrences_total"] == 3
    assert [item["position"] for item in body["occurrences"]] == [1, 2, 3]
    assert [item["comicvine_volume_id"] for item in body["occurrences"]] == [
        "2000-volume-comicvine",
        None,
        None,
    ]


@pytest.mark.asyncio
async def test_lookup_paginates_occurrences_without_losing_totals(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Occurrences page through the catalog while the totals stay whole."""
    source = await _seed_source(async_db)
    alpha = await _seed_list(
        async_db,
        source=source,
        name="Alpha Reading",
        path="Marvel/Alpha.cbl",
    )
    beta = await _seed_list(
        async_db,
        source=source,
        name="Beta Reading",
        path="Marvel/Beta.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-paged")
    for position in range(1, 4):
        await _seed_entry(
            async_db,
            source_list=alpha,
            position=position,
            issue_identity=issue_identity,
        )
    for position in range(1, 3):
        await _seed_entry(
            async_db,
            source_list=beta,
            position=position,
            issue_identity=issue_identity,
        )
    await async_db.commit()

    first = await auth_client.get(f"{LOOKUP_URL}/4000-paged?limit=2&offset=0")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["occurrences_total"] == 5
    assert first_body["lists_total"] == 2
    assert first_body["occurrences_offset"] == 0
    assert first_body["occurrences_limit"] == 2
    assert len(first_body["occurrences"]) == 2

    second = await auth_client.get(f"{LOOKUP_URL}/4000-paged?limit=2&offset=2")
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["occurrences_total"] == 5
    assert second_body["lists_total"] == 2
    assert second_body["occurrences_offset"] == 2
    assert len(second_body["occurrences"]) == 2

    third = await auth_client.get(f"{LOOKUP_URL}/4000-paged?limit=2&offset=4")
    assert third.status_code == 200, third.text
    third_body = third.json()
    assert third_body["occurrences_total"] == 5
    assert len(third_body["occurrences"]) == 1

    paged_positions = [
        (item["list_id"], item["position"])
        for body in (first_body, second_body, third_body)
        for item in body["occurrences"]
    ]
    assert paged_positions == [
        (alpha.id, 1),
        (alpha.id, 2),
        (alpha.id, 3),
        (beta.id, 1),
        (beta.id, 2),
    ]


@pytest.mark.asyncio
async def test_lookup_returns_empty_result_for_unknown_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An identity nobody owns and no source holds returns an empty result."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Other Reading",
        path="Marvel/Other.cbl",
    )
    other_identity = await _seed_identity(async_db, external_id="4000-other")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=other_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-unknown")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comicvine_issue_id"] == "4000-unknown"
    assert body["occurrences_total"] == 0
    assert body["lists_total"] == 0
    assert body["occurrences"] == []


@pytest.mark.asyncio
async def test_lookup_excludes_inactive_source_lists(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A list removed from the current mirror revision is not in the catalog."""
    source = await _seed_source(async_db)
    archived = await _seed_list(
        async_db,
        source=source,
        name="Archived Reading",
        path="Marvel/Archived.cbl",
        active=False,
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-archived")
    await _seed_entry(
        async_db,
        source_list=archived,
        position=1,
        issue_identity=issue_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-archived")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["occurrences_total"] == 0
    assert body["lists_total"] == 0
    assert body["occurrences"] == []


@pytest.mark.asyncio
async def test_lookup_never_constrains_to_user_owned_issues(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The same query returns the same answer for readers with different collections."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Shared Reading",
        path="Marvel/Shared.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-shared")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
    )

    owner = User(username="cbl_lookup_owner", created_at=datetime.now(UTC))
    empty_reader = User(username="cbl_lookup_empty", created_at=datetime.now(UTC))
    async_db.add_all([owner, empty_reader])
    await async_db.flush()

    owned_thread = Thread(
        title="Owned Mister Miracle",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=owner.id,
    )
    async_db.add(owned_thread)
    await async_db.flush()

    owned_issue = Issue(
        thread_id=owned_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(owned_issue)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=owned_issue.id,
            external_identity_id=issue_identity.id,
            status="confirmed",
        )
    )
    await async_db.commit()

    owner_token = create_access_token(data={"sub": owner.username, "jti": "owner"})
    empty_token = create_access_token(data={"sub": empty_reader.username, "jti": "empty"})

    owner_response = await client.get(
        f"{LOOKUP_URL}/4000-shared",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    empty_response = await client.get(
        f"{LOOKUP_URL}/4000-shared",
        headers={"Authorization": f"Bearer {empty_token}"},
    )

    assert owner_response.status_code == 200, owner_response.text
    assert empty_response.status_code == 200, empty_response.text
    assert owner_response.json() == empty_response.json()
    assert owner_response.json()["occurrences_total"] == 1
    assert owner_response.json()["lists_total"] == 1


@pytest.mark.asyncio
async def test_lookup_is_read_only(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The reverse lookup never creates or changes reader-owned rows."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Read Only Reading",
        path="Marvel/Read Only.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-read-only")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
    )
    await async_db.commit()

    async_db.expire_all()
    before = {
        "issues": await async_db.scalar(select(func.count()).select_from(Issue)),
        "threads": await async_db.scalar(select(func.count()).select_from(Thread)),
        "mappings": await async_db.scalar(
            select(func.count()).select_from(IssueExternalIdentityMapping)
        ),
        "identities": await async_db.scalar(
            select(func.count()).select_from(ExternalIdentity)
        ),
        "entries": await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)),
    }

    response = await auth_client.get(f"{LOOKUP_URL}/4000-read-only")
    assert response.status_code == 200, response.text

    async_db.expire_all()
    after = {
        "issues": await async_db.scalar(select(func.count()).select_from(Issue)),
        "threads": await async_db.scalar(select(func.count()).select_from(Thread)),
        "mappings": await async_db.scalar(
            select(func.count()).select_from(IssueExternalIdentityMapping)
        ),
        "identities": await async_db.scalar(
            select(func.count()).select_from(ExternalIdentity)
        ),
        "entries": await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)),
    }
    assert after == before


@pytest.mark.asyncio
async def test_lookup_sanitizes_production_mirror_repository(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The production CBL mirror path never reaches the reader (#3365)."""
    source = await _seed_source(
        async_db,
        repository="/mnt/bigdata/CBL-ReadingLists",
        revision_sha="def456",
    )
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Mirror Reading",
        path="Marvel/Mirror.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-mirror")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
    )
    await async_db.commit()

    response = await auth_client.get(f"{LOOKUP_URL}/4000-mirror")
    assert response.status_code == 200, response.text
    occurrence = response.json()["occurrences"][0]
    assert occurrence["source_repository"] == "JoshCLWren/CBL-ReadingLists"
    assert "/mnt/" not in occurrence["source_repository"]
    assert occurrence["source_ref"] == "JoshCLWren/CBL-ReadingLists:Marvel/Mirror.cbl"


@pytest.mark.asyncio
async def test_lookup_requires_authentication(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An unauthenticated reader cannot run the shared-catalog reverse lookup."""
    source = await _seed_source(async_db)
    source_list = await _seed_list(
        async_db,
        source=source,
        name="Private Reading",
        path="Marvel/Private.cbl",
    )
    issue_identity = await _seed_identity(async_db, external_id="4000-private")
    await _seed_entry(
        async_db,
        source_list=source_list,
        position=1,
        issue_identity=issue_identity,
    )
    await async_db.commit()

    response = await client.get(f"{LOOKUP_URL}/4000-private")
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_lookup_rejects_blank_comicvine_issue_id(
    auth_client: AsyncClient,
) -> None:
    """A blank Comic Vine issue ID is a request error, not an empty catalog."""
    response = await auth_client.get(f"{LOOKUP_URL}/%20")
    assert response.status_code == 422, response.text
