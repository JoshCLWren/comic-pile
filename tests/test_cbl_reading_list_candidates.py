"""Issue #4012: CBL coverage comparison for a comic and an owned Reading List."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
)

COMPARE_URL = "/api/v1/issue-identity/cbl-sources/compare"
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
    declared_issue_count: int | None = 3,
) -> CBLSourceList:
    """Persist one active source list with a deterministic content hash."""
    row = CBLSourceList(
        source_id=source.id,
        source_path=path,
        name=name,
        declared_issue_count=declared_issue_count,
        content_hash=sha256(f"{name}|{path}".encode()).hexdigest(),
        revision_sha=source.revision_sha,
        active=True,
    )
    db.add(row)
    await db.flush()
    return row


async def _seed_identity(
    db: AsyncSession,
    *,
    external_id: str,
    entity_type: str = "issue",
) -> ExternalIdentity:
    """Persist one Comic Vine external identity."""
    identity = ExternalIdentity(
        provider="comicvine",
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
    issue_identity: ExternalIdentity,
    series_name: str = "Mister Miracle",
    issue_number: str = "1",
    volume_year: int | None = 1985,
) -> CBLSourceEntry:
    """Persist one ordered source occurrence bound to an exact issue identity."""
    entry = CBLSourceEntry(
        list_id=source_list.id,
        position=position,
        series_name=series_name,
        issue_number=issue_number,
        volume_year=volume_year,
        publication_year=volume_year,
        external_issue_identity_id=issue_identity.id,
    )
    db.add(entry)
    await db.flush()
    return entry






async def _seed_three_candidates(
    db: AsyncSession,
) -> dict[str, CBLSourceList]:
    """Seed the acceptance lists ``A,B,C``, ``A,A,B``, and reordered ``C,A,B``.

    Returns:
        Mapping of label to source list for assertions.
    """
    source = await _seed_source(db)
    a = await _seed_identity(db, external_id="4000-comic-a")
    b = await _seed_identity(db, external_id="4000-comic-b")
    c = await _seed_identity(db, external_id="4000-comic-c")
    in_order = await _seed_list(
        db, source=source, name="Alpha In Order", path="Marvel/Alpha.cbl"
    )
    duplicated = await _seed_list(
        db, source=source, name="Beta Duplicated", path="Marvel/Beta.cbl"
    )
    reordered = await _seed_list(
        db, source=source, name="Gamma Reordered", path="Marvel/Gamma.cbl"
    )
    for position, identity in enumerate((a, b, c), start=1):
        await _seed_entry(
            db, source_list=in_order, position=position, issue_identity=identity
        )
    for position, identity in enumerate((a, a, b), start=1):
        await _seed_entry(
            db, source_list=duplicated, position=position, issue_identity=identity
        )
    for position, identity in enumerate((c, a, b), start=1):
        await _seed_entry(
            db, source_list=reordered, position=position, issue_identity=identity
        )
    return {"in_order": in_order, "duplicated": duplicated, "reordered": reordered}


@pytest.mark.asyncio
async def test_compare_ranks_full_order_above_duplicates_and_reordering(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """``A,B,C`` outranks reordered ``C,A,B`` and duplicate ``A,A,B``."""
    lists = await _seed_three_candidates(async_db)
    await async_db.commit()

    response = await auth_client.post(
        COMPARE_URL,
        json={"comicvine_issue_ids": ["4000-comic-a", "4000-comic-b", "4000-comic-c"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["input_total"] == 3
    assert body["candidates_total"] == 3
    by_id = {match["list_id"]: match for match in body["candidates"]}
    ordered_ids = [match["list_id"] for match in body["candidates"]]
    assert ordered_ids == [
        lists["in_order"].id,
        lists["reordered"].id,
        lists["duplicated"].id,
    ]

    in_order = by_id[lists["in_order"].id]
    assert in_order["matched_input_count"] == 3
    assert in_order["matched_occurrence_count"] == 3
    assert in_order["duplicate_match_count"] == 0
    assert in_order["source_only_issue_count"] == 0
    assert in_order["input_coverage_percentage"] == 100
    assert in_order["source_coverage_percentage"] == 100
    assert in_order["order_status"] == "same_order"
    assert in_order["order_pair_count"] == 3
    assert in_order["order_disagreement_count"] == 0
    assert in_order["missing_input_ids"] == []
    assert in_order["score"] == 100

    duplicated = by_id[lists["duplicated"].id]
    assert duplicated["entries_total"] == 3
    assert duplicated["distinct_source_issues"] == 2
    assert duplicated["matched_input_count"] == 2
    assert duplicated["matched_occurrence_count"] == 3
    assert duplicated["duplicate_match_count"] == 1
    assert duplicated["input_coverage_percentage"] == 67
    assert duplicated["order_status"] == "same_order"
    assert duplicated["missing_input_ids"] == ["4000-comic-c"]

    reordered = by_id[lists["reordered"].id]
    assert reordered["matched_input_count"] == 3
    assert reordered["input_coverage_percentage"] == 100
    assert reordered["order_status"] == "reordered"
    assert reordered["order_pair_count"] == 3
    assert reordered["order_disagreement_count"] == 2
    assert reordered["score"] < in_order["score"]
    assert duplicated["score"] < reordered["score"]


@pytest.mark.asyncio
async def test_compare_deduplicates_repeated_input_ids(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A duplicated input list never inflates coverage or occurrence counts."""
    lists = await _seed_three_candidates(async_db)
    await async_db.commit()

    response = await auth_client.post(
        COMPARE_URL,
        json={
            "comicvine_issue_ids": [
                "4000-comic-a",
                "4000-comic-a",
                "4000-comic-b",
                "4000-comic-c",
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["comicvine_issue_ids"] == [
        "4000-comic-a",
        "4000-comic-b",
        "4000-comic-c",
    ]
    assert body["input_total"] == 3
    by_id = {match["list_id"]: match for match in body["candidates"]}
    duplicated = by_id[lists["duplicated"].id]
    assert duplicated["matched_input_count"] == 2
    assert duplicated["matched_occurrence_count"] == 3
    assert duplicated["duplicate_match_count"] == 1
    assert by_id[lists["in_order"].id]["matched_input_count"] == 3


@pytest.mark.asyncio
async def test_same_title_and_number_never_matches_another_volume(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Exact Comic Vine IDs decide matches; titles and numbers never do."""
    source = await _seed_source(async_db)
    same_title = await _seed_list(
        db=async_db,
        source=source,
        name="Same Title Different Volume",
        path="Marvel/Same Title.cbl",
    )
    target_identity = await _seed_identity(async_db, external_id="4000-target-volume")
    other_volume_identity = await _seed_identity(
        async_db, external_id="4000-other-volume"
    )
    await _seed_entry(
        async_db,
        source_list=same_title,
        position=1,
        issue_identity=target_identity,
        series_name="Mister Miracle",
        issue_number="1",
        volume_year=1985,
    )
    await _seed_entry(
        async_db,
        source_list=same_title,
        position=2,
        issue_identity=other_volume_identity,
        series_name="Mister Miracle",
        issue_number="1",
        volume_year=2017,
    )
    await async_db.commit()

    compare = await auth_client.post(
        COMPARE_URL,
        json={"comicvine_issue_ids": ["4000-target-volume"]},
    )
    assert compare.status_code == 200, compare.text
    body = compare.json()
    assert body["candidates_total"] == 1
    assert body["candidates"][0]["matched_input_count"] == 1
    assert body["candidates"][0]["matched_occurrence_count"] == 1
    assert body["candidates"][0]["matched_input_ids"] == ["4000-target-volume"]

    unmatched = await auth_client.post(
        COMPARE_URL,
        json={"comicvine_issue_ids": ["4000-title-only-lookalike"]},
    )
    assert unmatched.status_code == 200, unmatched.text
    assert unmatched.json()["candidates_total"] == 0
    assert unmatched.json()["candidates"] == []

    lookup = await auth_client.get(f"{LOOKUP_URL}/4000-title-only-lookalike")
    assert lookup.status_code == 200, lookup.text
    assert lookup.json()["occurrences_total"] == 0




