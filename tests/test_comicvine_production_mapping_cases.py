"""Regressions from actual Tom Strong and Starman mapping states, captured 2026-10-19.

The fixture contains public provider metadata, issue labels and mapping IDs only. It excludes
user IDs, credentials, reading progress and history. Provider reads are replayed so CI covers
the production integration shapes without depending on ComicVine availability.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.thread_repository import fetch_comicvine_mapping_health

PREVIEW_URL = "/api/v1/catalog/series-mappings/preview"
COMMIT_URL = "/api/v1/catalog/series-mappings/commit"
CASES = json.loads(
    (Path(__file__).parent / "fixtures/comicvine/production_mapping_cases.json").read_text()
)["cases"]


async def _seed_case(
    db: AsyncSession, user_id: int, case_index: int
) -> tuple[list[Issue], AsyncMock]:
    """Recreate a production case under the test user with fresh local primary keys."""
    case = CASES[case_index]
    thread = Thread(
        title=case["title"], user_id=user_id, format="Comic", status="active",
        queue_position=90, issues_remaining=len(case["issues"]),
        total_issues=len(case["issues"]),
    )
    db.add(thread)
    await db.flush()
    issues = []
    identities: dict[str, ExternalIdentity] = {}
    for position, source in enumerate(case["issues"], 1):
        issue = Issue(
            thread_id=thread.id, issue_number=source["issue_number"],
            position=position, status="unread",
        )
        db.add(issue)
        await db.flush()
        issues.append(issue)
        if source["external_id"] is None:
            continue
        identity = identities.get(source["external_id"])
        if identity is None:
            identity = ExternalIdentity(
                provider="comicvine", entity_type="issue", external_id=source["external_id"],
                metadata_json=source["metadata"],
            )
            db.add(identity)
            await db.flush()
            identities[source["external_id"]] = identity
        db.add(IssueExternalIdentityMapping(
            issue_id=issue.id, external_identity_id=identity.id, status="confirmed",
            evidence_source="broad_cbl_volume_representation",
        ))
    # Real imported series stubs can exist without even a name. This triggered the 500.
    db.add(ExternalIdentity(
        provider="comicvine", entity_type="series", external_id=str(case["volume"]["id"]),
        metadata_json={},
    ))
    await db.commit()
    for issue in issues:
        await db.refresh(issue)
    client = AsyncMock()
    client.fetch_volume.return_value = SimpleNamespace(payload={"results": case["volume"]})
    client.fetch_volume_issues.return_value = case["roster"]
    return issues, client


@pytest.mark.parametrize("mode", ["confirmed_origin", "queue_thread_bootstrap"])
async def test_tom_strong_blank_confirmations_offer_usable_metadata(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data, mode: str
) -> None:
    """Both Roll's sibling flow and Queue update all 29 blank identities without unlinking."""
    issues, client = await _seed_case(async_db, sample_data["user"].id, 0)
    series = (await async_db.scalars(select(ExternalIdentity).where(
        ExternalIdentity.entity_type == "series", ExternalIdentity.external_id == "6566"
    ))).one()
    series_id = series.id
    series.metadata_json = {"description": "Existing deep volume details"}
    await async_db.commit()
    before = dict((await async_db.execute(select(
        IssueExternalIdentityMapping.issue_id, IssueExternalIdentityMapping.external_identity_id
    ))).all())
    thread_id = issues[0].thread_id
    health = await fetch_comicvine_mapping_health(async_db, {thread_id})
    assert health[thread_id]["metadata_missing_count"] == 29
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[6].id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": mode,
        })
        assert response.status_code == 200
        plan = response.json()
        assert plan["provider_series"]["name"] == "Tom Strong"
        assert plan["scope"]["status"] == "available"
        refresh_rows = [row for row in plan["rows"] if row["metadata_refresh_required"]]
        assert len(refresh_rows) == 29
        assert all(row["classification"] == "already_confirmed" for row in refresh_rows)
        assert all(row["default_selected"] for row in refresh_rows)
        # The preview itself never fills or changes the identity.
        blank = await async_db.get(ExternalIdentity, before[refresh_rows[0]["issue_id"]])
        assert blank is not None and blank.metadata_json == {}
        request = {
            "preview_token": plan["preview_token"], "idempotency_key": f"tom-strong-{mode}",
            "approved_row_ids": [row["row_id"] for row in refresh_rows],
        }
        # Roster metadata must be durable even when deep singular-issue hydration cannot run.
        with patch("app.services.catalog_series_commit._hydrate_after_commit", new=AsyncMock()):
            saved = await auth_client.post(COMMIT_URL, json=request)
        assert saved.status_code == 200, saved.text
        assert len(saved.json()["confirmed_issue_ids"]) == 29
        replay = await auth_client.post(COMMIT_URL, json=request)
        assert replay.status_code == 200 and replay.json() == saved.json()

    async_db.expire_all()
    after = dict((await async_db.execute(select(
        IssueExternalIdentityMapping.issue_id, IssueExternalIdentityMapping.external_identity_id
    ))).all())
    assert after == before
    series = await async_db.get(ExternalIdentity, series_id)
    assert series is not None
    assert series.metadata_json["description"] == "Existing deep volume details"
    assert series.metadata_json["name"] == "Tom Strong"
    health = await fetch_comicvine_mapping_health(async_db, {thread_id})
    assert health[thread_id]["metadata_missing_count"] == 0
    for row in refresh_rows:
        identity = await async_db.get(ExternalIdentity, before[row["issue_id"]])
        assert identity is not None
        assert identity.metadata_json["issue_number"] == row["issue_number"]
        volume = identity.metadata_json["volume"]
        assert isinstance(volume, dict) and volume["id"] == 6566
        assert identity.metadata_json["primary_image"]
        # This is the actual read API used by Roll, not just the persistence flag.
        intelligence = await auth_client.get(f"/api/v1/issues/{row['issue_id']}/comicvine")
        assert intelligence.status_code == 200, intelligence.text
        assert intelligence.json()["image_url"]
        assert intelligence.json()["series_name"] == "Tom Strong"


async def test_starman_mixed_thread_keeps_existing_links_and_explains_leftovers(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data
) -> None:
    """An all-confirmed main volume still produces a visible plan for a mixed reading thread."""
    issues, client = await _seed_case(async_db, sample_data["user"].id, 1)
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[0].id, "provider": "comicvine",
            "provider_series_external_id": "5259", "scope_mode": "queue_thread_bootstrap",
        })
    assert response.status_code == 200
    plan = response.json()
    assert plan["scope"]["status"] == "available"
    assert plan["counts"]["already_confirmed"] > 70
    assert plan["counts"]["safe_exact_match"] == 0
    assert len([row for row in plan["rows"] if row["thread_id"] is not None]) == 102
    shade_rows = [row for row in plan["rows"] if row["issue_number"].startswith("The Shade")]
    assert len(shade_rows) == 12
    assert all(row["classification"] == "needs_review_ambiguous" for row in shade_rows)
    named_rows = [row for row in plan["rows"] if row["issue_number"] in (
        "JSA: All Stars 4", "Stars and S.T.R.I.P.E. 0", "Starman/Congorilla 1"
    )]
    assert len(named_rows) == 3
    assert all(row["classification"] == "needs_review_ambiguous" for row in named_rows)
    assert not any(row["metadata_refresh_required"] for row in named_rows)
    assert not any(row["default_selected"] for row in shade_rows)
    assert any(row["metadata_refresh_required"] for row in plan["rows"])
    # An already-confirmed issue with metadata is never accepted as a refresh write.
    linked = next(row for row in plan["rows"] if row["classification"] == "already_confirmed"
                  and not row["metadata_refresh_required"])
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        rejected = await auth_client.post(COMMIT_URL, json={
            "preview_token": plan["preview_token"], "idempotency_key": "starman-no-rewrite",
            "approved_row_ids": [linked["row_id"]],
        })
    assert rejected.status_code == 422


async def test_known_series_provider_outage_is_retryable(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data
) -> None:
    """A locally known series does not disguise an integration outage as unsafe user data."""
    issues, _ = await _seed_case(async_db, sample_data["user"].id, 0)
    with patch("app.services.catalog._load_provider_volume_roster", side_effect=HTTPException(
        status_code=503, detail="provider_unavailable"
    )):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[0].id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": "queue_thread_bootstrap",
        })
    assert response.status_code == 503


async def test_metadata_refresh_approval_becomes_stale_after_concurrent_hydration(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data
) -> None:
    """An old token cannot authorize a refresh that the current server plan no longer offers."""
    issues, client = await _seed_case(async_db, sample_data["user"].id, 0)
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[6].id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": "queue_thread_bootstrap",
        })
        plan = response.json()
        target = next(row for row in plan["rows"] if row["metadata_refresh_required"])
        identity = (await async_db.execute(select(ExternalIdentity).join(
            IssueExternalIdentityMapping,
            IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
        ).where(IssueExternalIdentityMapping.issue_id == target["issue_id"]))).scalar_one()
        identity.metadata_json = {"issue_number": target["issue_number"], "volume": {"name": "Tom Strong"}}
        await async_db.commit()
        refused = await auth_client.post(COMMIT_URL, json={
            "preview_token": plan["preview_token"], "idempotency_key": "stale-metadata",
            "approved_row_ids": [target["row_id"]],
        })
    assert refused.status_code == 409
    assert refused.json()["detail"] == "preview_stale"


async def test_generic_missing_series_name_is_safe_during_provider_outage(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data
) -> None:
    """The exact production ValidationError shape stays a valid, non-mutating response."""
    issues, _ = await _seed_case(async_db, sample_data["user"].id, 0)
    with patch("app.services.catalog._load_provider_volume_roster", side_effect=HTTPException(
        status_code=503, detail="provider_unavailable"
    )):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[0].id, "provider": "comicvine",
            "provider_series_external_id": "6566",
        })
    assert response.status_code == 200
    assert response.json()["provider_series"]["name"] is None
    assert response.json()["preview_token"] is None


@pytest.mark.parametrize("invalid_id", [None, 0, "not-an-id"])
async def test_provider_rows_without_real_ids_are_never_offered(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data, invalid_id: object
) -> None:
    """A malformed provider roster cannot turn a known blank link into a phantom identity."""
    issues, client = await _seed_case(async_db, sample_data["user"].id, 0)
    roster = [dict(row) for row in CASES[0]["roster"]]
    target = next(row for row in roster if row["issue_number"] == "8")
    target["id"] = invalid_id
    client.fetch_volume_issues.return_value = roster
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        response = await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issues[6].id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": "queue_thread_bootstrap",
        })
    assert response.status_code == 200
    row = next(row for row in response.json()["rows"] if row["issue_number"] == "8")
    assert row["classification"] == "unresolved"
    assert row["metadata_refresh_required"] is False
    assert row["default_selected"] is False


@pytest.mark.parametrize("stored_volume", [{"id": 6566}, {"id": 6566, "name": ""},
                                         {"id": 999, "name": None}])
async def test_update_fills_partial_volume_references_without_deep_hydration(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data,
    stored_volume: dict[str, object],
) -> None:
    """A successful Update must expose a series name even when an imported volume is partial."""
    issues, client = await _seed_case(async_db, sample_data["user"].id, 0)
    issue_id = issues[7].id
    identity = (await async_db.scalars(select(ExternalIdentity).join(
        IssueExternalIdentityMapping,
        IssueExternalIdentityMapping.external_identity_id == ExternalIdentity.id,
    ).where(IssueExternalIdentityMapping.issue_id == issue_id))).one()
    identity_id = identity.id
    identity.metadata_json = {"volume": stored_volume, "description": "Retain deep description",
                              "creator_credits": [{"name": "Retain creator", "role": "writer"}]}
    await async_db.commit()
    with patch("app.services.catalog._get_comicvine_client", return_value=client):
        plan = (await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issue_id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": "queue_thread_bootstrap",
        })).json()
        with patch("app.services.catalog_series_commit._hydrate_after_commit", new=AsyncMock()):
            saved = await auth_client.post(COMMIT_URL, json={
                "preview_token": plan["preview_token"], "idempotency_key": "partial-volume",
                "approved_row_ids": [f"issue:{issue_id}"],
            })
        assert saved.status_code == 200, saved.text
        after = (await auth_client.post(PREVIEW_URL, json={
            "origin_issue_id": issue_id, "provider": "comicvine",
            "provider_series_external_id": "6566", "scope_mode": "queue_thread_bootstrap",
        })).json()
    row = next(row for row in after["rows"] if row["issue_id"] == issue_id)
    assert row["metadata_refresh_required"] is False
    intelligence = await auth_client.get(f"/api/v1/issues/{issue_id}/comicvine")
    assert intelligence.json()["series_name"] == "Tom Strong"
    assert intelligence.json()["image_url"]
    await async_db.refresh(identity)
    assert identity.id == identity_id
    assert identity.metadata_json["description"] == "Retain deep description"
    assert identity.metadata_json["creator_credits"] == [{"name": "Retain creator", "role": "writer"}]


@pytest.mark.parametrize("number", ["JSA: All Stars 4", "The Shade (2011) 1", "1/2", "1A", "#1"])
def test_named_and_fractional_issue_labels_never_normalize_to_main_series_numbers(number: str) -> None:
    """Discarding a title, slash, or variant suffix must never create a safe exact match."""
    from app.services.catalog import _normalize_issue_number

    assert _normalize_issue_number(number) == ""


@pytest.mark.parametrize(("number", "expected"), [("1.", "1"), ("1,000,000", "1000000")])
def test_numeric_punctuation_keeps_duplicate_detection(number: str, expected: str) -> None:
    """Benign legacy numeric spellings still participate in unique-cardinality checks."""
    from app.services.catalog import _normalize_issue_number

    assert _normalize_issue_number(number) == expected
