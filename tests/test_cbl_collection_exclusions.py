"""Collection exclusions are identity-based and cannot be overridden by CBL import."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.collection_exclusion import CollectionExclusion
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.services.cbl_source_identity_resolution import report_cbl_source_identity_resolution
from app.services.collection_exclusion_guard import (
    CollectionGuard,
    load_collection_guard,
    normalize_volume,
)
from tests.conftest import get_or_create_user_async


async def _source(db: AsyncSession) -> tuple[CBLSourceList, list[ExternalIdentity]]:
    """Include two absent excluded volumes and one allowed volume, with source aliases."""
    source = CBLSource(
        repository="JoshCLWren/collection-guard-fixture",
        revision_sha="abc",
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    reading_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Absolute.cbl",
        name="Absolute exclusion fixture",
        content_hash="hash",
        revision_sha="abc",
        active=True,
        declared_issue_count=3,
    )
    db.add(reading_list)
    await db.flush()
    volumes = []
    for position, (name, volume) in enumerate(
        (
            ("ABSOLUTE  FLASH (alternate spelling)", "4050-10001"),
            ("Absolute Green Lantern", "10002"),
            ("Absolute Batman", "10003"),
        )
    ):
        series_identity = ExternalIdentity(
            provider="comicvine", entity_type="series", external_id=volume, metadata_json={}
        )
        issue_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=str(20001 + position),
            metadata_json={"volume_id": volume},
        )
        db.add_all([series_identity, issue_identity])
        await db.flush()
        db.add(
            CBLSourceEntry(
                list_id=reading_list.id,
                position=position,
                series_name=name,
                issue_number="1",
                volume_year=2025,
                external_series_identity_id=series_identity.id,
                external_issue_identity_id=issue_identity.id,
            )
        )
        volumes.append(series_identity)
    await db.commit()
    return reading_list, volumes


async def test_preview_and_explicit_include_cannot_restore_excluded_volumes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Absent Flash/Green Lantern stay out across aliases, import and subsequent retries."""
    user = await get_or_create_user_async(async_db)
    source, _ = await _source(async_db)
    async_db.add_all(
        [
            CollectionExclusion(user_id=user.id, provider="comicvine", external_volume_id="10001"),
            CollectionExclusion(
                user_id=user.id, provider="comicvine", external_volume_id="4050-10002"
            ),
        ]
    )
    await async_db.commit()
    preview = await auth_client.get(f"/api/v1/issue-identity/cbl/{source.id}/adoption-preview")
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert [entry["adoption_decision"] for entry in data["entries"]] == [
        "excluded",
        "excluded",
        "would_create_missing",
    ]
    assert all(
        row["collection_exclusion_reason"] == "collection_volume_excluded"
        for row in data["entries"][:2]
    )
    payload = {
        "content_hash": "hash",
        "revision_sha": "abc",
        "entry_decisions": {str(i): "include" for i in range(3)},
    }
    response = await auth_client.post(f"/api/v1/cbl/{source.id}/adoption-commit", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["excluded_positions"] == [0, 1]
    assert response.json()["created_positions"] == [2]
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 1
    titles = list((await async_db.scalars(select(Thread.title))).all())
    assert titles == ["CBL: Absolute Batman (2025)"]
    # Reconciliation itself also carries the exclusion, with every source position retained.
    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source.id
    )
    assert [row.status for row in rows[:2]] == ["collection_excluded", "collection_excluded"]
    assert all(row.chosen_issue_id is None for row in rows[:2])


async def test_exclusion_added_after_preview_is_rechecked_at_commit(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A reviewed source fingerprint does not freeze collection permission."""
    user = await get_or_create_user_async(async_db)
    source, _ = await _source(async_db)
    preview = await auth_client.get(f"/api/v1/issue-identity/cbl/{source.id}/adoption-preview")
    assert preview.status_code == 200
    assert preview.json()["summary"]["missing_would_create_count"] == 3
    response = await auth_client.post(
        "/api/v1/collection-exclusions",
        json={
            "provider": "comicvine",
            "external_volume_id": "10001",
        },
    )
    assert response.status_code == 200, response.text
    result = await auth_client.post(
        f"/api/v1/cbl/{source.id}/adoption-commit",
        json={
            "content_hash": "hash",
            "revision_sha": "abc",
        },
    )
    assert result.status_code == 201, result.text
    assert result.json()["excluded_positions"] == [0]
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 2
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(CollectionExclusion)
            .where(CollectionExclusion.user_id == user.id)
        )
        == 1
    )


def test_identity_conflicts_and_missing_identity_fail_closed_without_name_guessing() -> None:
    """Names and explicit Include choices never override uncertain volume identity."""
    guard = CollectionGuard(volumes={normalize_volume("comicvine", "10001"): 5})
    assert guard.check({"series_name": "Absolute Flash"}) is not None
    decision = guard.check({"comicvine_series_id": "10003", "volume_id": "4050-10001"})
    assert decision is not None
    assert decision.exclusion_ids == (5,)
    assert guard.check({"comicvine_series_id": "10003"}) is None
    decision = guard.check({"comicvine_series_id": "10003", "volume_id": "10004"})
    assert decision is not None and decision.reason == "collection_identity_requires_review"
    assert CollectionGuard(issues={7: 1}).check({"resolved_issue_id": 7}) is not None
    assert (
        CollectionGuard(threads={9: 2}, issue_threads={7: 9}).check({"resolved_issue_id": 7})
        is not None
    )


def test_source_identity_evidence_reaches_local_exclusions() -> None:
    """Confirmed source identities resolve the owned target preview cannot see yet."""
    guard = CollectionGuard(
        threads={9: 2},
        issues={7: 1},
        issue_threads={7: 9},
        issue_targets={5: {7}},
        series_threads={3: {9}},
    )
    reused = guard.check({"external_issue_identity_id": 5})
    assert reused is not None and reused.reason == "collection_issue_excluded"
    assert reused.exclusion_ids == (1,)
    landed = guard.check({"external_series_identity_id": 3})
    assert landed is not None and landed.reason == "collection_thread_excluded"
    assert landed.exclusion_ids == (2,)
    assert guard.check({"external_series_identity_id": 4}) is None
    assert guard.check({"external_issue_identity_id": 6}) is None


async def test_excluded_thread_target_excludes_one_position_instead_of_failing(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A Thread exclusion reached only at commit stays a per-position outcome."""
    user = await get_or_create_user_async(async_db)
    source, volumes = await _source(async_db)
    thread = Thread(
        user_id=user.id,
        title="CBL: ABSOLUTE  FLASH (alternate spelling)",
        format="comic",
        queue_position=1,
        status="active",
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=volumes[0].id,
            status="confirmed",
            evidence_source="cbl_adoption_commit",
        )
    )
    exclusion = CollectionExclusion(user_id=user.id, thread_id=thread.id)
    async_db.add(exclusion)
    await async_db.commit()

    preview = await auth_client.get(f"/api/v1/issue-identity/cbl/{source.id}/adoption-preview")
    assert preview.status_code == 200, preview.text
    first = preview.json()["entries"][0]
    assert first["adoption_decision"] == "excluded"
    assert first["collection_exclusion_reason"] == "collection_thread_excluded"
    assert first["collection_exclusion_ids"] == [exclusion.id]

    response = await auth_client.post(
        f"/api/v1/cbl/{source.id}/adoption-commit",
        json={"content_hash": "hash", "revision_sha": "abc"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["excluded_positions"] == [0]
    assert response.json()["created_positions"] == [1, 2]
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 2
    # The refused position must not leave a partially created series Thread behind.
    titles = set((await async_db.scalars(select(Thread.title))).all())
    assert titles == {
        "CBL: ABSOLUTE  FLASH (alternate spelling)",
        "CBL: Absolute Green Lantern (2025)",
        "CBL: Absolute Batman (2025)",
    }


@pytest.mark.parametrize(
    "provider,value,expected",
    [
        ("ComicVine", " 4050-0010001 ", ("comicvine", "10001")),
        ("other", "4050-10001", ("other", "4050-10001")),
    ],
)
def test_normalization_uses_provider_identity_not_source_spelling(
    provider, value, expected
) -> None:
    """ComicVine's volume prefix is equivalent only in its own provider namespace."""
    assert normalize_volume(provider, value) == expected


@pytest.mark.parametrize("target", ["issue_id", "thread_id"])
async def test_owned_material_remains_excluded_in_preview(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    target: str,
) -> None:
    """Existing owned material also respects explicit Thread and Issue exclusions."""
    user = await get_or_create_user_async(async_db)
    source, _ = await _source(async_db)
    result = await auth_client.post(
        f"/api/v1/cbl/{source.id}/adoption-commit",
        json={
            "content_hash": "hash",
            "revision_sha": "abc",
        },
    )
    assert result.status_code == 201, result.text
    issue = (await async_db.scalars(select(Issue).order_by(Issue.id))).first()
    assert issue is not None
    exclusion = CollectionExclusion(user_id=user.id)
    if target == "issue_id":
        exclusion.issue_id = issue.id
    else:
        exclusion.thread_id = issue.thread_id
    async_db.add(exclusion)
    await async_db.commit()
    response = await auth_client.get(f"/api/v1/issue-identity/cbl/{source.id}/adoption-preview")
    assert response.status_code == 200, response.text
    assert response.json()["entries"][0]["adoption_decision"] == "excluded"
    assert response.json()["entries"][0]["collection_exclusion_ids"] == [exclusion.id]


async def test_new_exclusion_invalidates_an_old_adoption_receipt(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A previous successful import cannot replay an obsolete Include decision."""
    user = await get_or_create_user_async(async_db)
    source, _ = await _source(async_db)
    url = f"/api/v1/cbl/{source.id}/adoption-commit"
    payload = {"content_hash": "hash", "revision_sha": "abc"}
    first = await auth_client.post(url, json=payload)
    assert first.status_code == 201, first.text
    async_db.add(
        CollectionExclusion(user_id=user.id, provider="comicvine", external_volume_id="10001")
    )
    await async_db.commit()
    retry = await auth_client.post(url, json=payload)
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert retry.json()["excluded_positions"] == [0]
    assert retry.json()["created_positions"] == []
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 3


async def test_issue_catalog_volume_cannot_hide_in_a_different_thread(
    async_db: AsyncSession,
) -> None:
    """A consolidated annual keeps its own stable volume identity for exclusions."""
    user = await get_or_create_user_async(async_db)
    _, volumes = await _source(async_db)
    identity = (
        await async_db.scalars(
            select(ExternalIdentity).where(
                ExternalIdentity.entity_type == "issue", ExternalIdentity.external_id == "20001"
            )
        )
    ).one()
    series = CatalogSeries(canonical_external_identity_id=volumes[0].id)
    async_db.add(series)
    await async_db.flush()
    catalog_issue = CatalogIssue(
        canonical_external_identity_id=identity.id, catalog_series_id=series.id
    )
    thread = Thread(
        user_id=user.id,
        title="Mixed annuals",
        format="Comic",
        queue_position=1,
        status="active",
        issues_remaining=1,
    )
    async_db.add_all([catalog_issue, thread])
    await async_db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="Annual 1",
        position=1,
        status="unread",
        catalog_issue_id=catalog_issue.id,
    )
    exclusion = CollectionExclusion(
        user_id=user.id, provider="comicvine", external_volume_id="10001"
    )
    async_db.add_all([issue, exclusion])
    await async_db.commit()
    fact: dict[str, object] = {"resolved_issue_id": issue.id, "comicvine_series_id": "10003"}
    guard = await load_collection_guard(async_db, user.id, [fact])
    decision = guard.check(fact)
    assert decision is not None
    assert decision.exclusion_ids == (exclusion.id,)
