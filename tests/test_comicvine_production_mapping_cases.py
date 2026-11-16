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
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping

PREVIEW_URL = "/api/v1/catalog/series-mappings/preview"
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
