"""Tests for ComicVine identity resolution and metadata correction API endpoints."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.metadata_correction import IssueMetadataCorrection


def _issue_identity(external_id: str, metadata: dict[str, object]) -> ExternalIdentity:
    return ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.gamespot.com/issue/4000-{external_id}/",
        metadata_json=metadata,
    )


@pytest.mark.asyncio
async def test_issue_identity_state_unmapped(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An unmapped issue reports no confirmed identity."""
    thread = Thread(
        user_id=default_user.id,
        title="Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/comicvine/issues/{issue.id}/identity")

    assert response.status_code == 200
    body = response.json()
    assert body["issue_id"] == issue.id
    assert body["has_confirmed_identity"] is False
    assert body["confirmed_mappings"] == []
    assert body["candidate_mappings"] == []
    assert body["has_unresolved"] is False


@pytest.mark.asyncio
async def test_issue_identity_state_with_confirmed(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A confirmed mapping is visible in the identity state."""
    thread = Thread(
        user_id=default_user.id,
        title="Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    identity = _issue_identity(
        "500",
        {"name": "Test Issue", "issue_number": "1", "volume_id": 10, "volume_name": "Test"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
            evidence_source="user_confirmed",
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/comicvine/issues/{issue.id}/identity")

    assert response.status_code == 200
    body = response.json()
    assert body["has_confirmed_identity"] is True
    assert len(body["confirmed_mappings"]) == 1
    assert body["confirmed_mappings"][0]["comicvine_id"] == "500"


@pytest.mark.asyncio
async def test_issue_identity_ownership_enforcement(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Cannot inspect identity of another user's issue."""
    other_user = User(username="identity_other_user")
    async_db.add(other_user)
    await async_db.flush()
    other_thread = Thread(
        user_id=other_user.id,
        title="Other",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(other_thread)
    await async_db.flush()
    other_issue = Issue(thread_id=other_thread.id, issue_number="1", position=1, status="unread")
    async_db.add(other_issue)
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/comicvine/issues/{other_issue.id}/identity")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_confirm_identity_creates_mapping(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirming a ComicVine identity creates the mapping."""
    thread = Thread(
        user_id=default_user.id,
        title="Confirm Test",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    response = await auth_client.post(
        f"/api/v1/comicvine/issues/{issue.id}/identity:confirm",
        json={"comicvine_issue_id": 7777},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_confirmed_identity"] is True
    assert body["confirmed_mappings"][0]["comicvine_id"] == "7777"


@pytest.mark.asyncio
async def test_replace_identity_demotes_old(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Replacing identity demotes the old mapping to rejected."""
    thread = Thread(
        user_id=default_user.id,
        title="Replace Test",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    old_identity = _issue_identity(
        "1111",
        {"name": "Old Issue", "issue_number": "1"},
    )
    async_db.add(old_identity)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=old_identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await async_db.flush()

    response = await auth_client.post(
        f"/api/v1/comicvine/issues/{issue.id}/identity:replace",
        json={"comicvine_issue_id": 2222, "reason": "Wrong issue"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_confirmed_identity"] is True
    assert body["confirmed_mappings"][0]["comicvine_id"] == "2222"


@pytest.mark.asyncio
async def test_refresh_metadata_returns_comicvine_id(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Refresh endpoint returns the confirmed ComicVine ID."""
    thread = Thread(
        user_id=default_user.id,
        title="Refresh Test",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    identity = _issue_identity(
        "3333",
        {"name": "Refresh Issue", "issue_number": "1"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await async_db.flush()

    response = await auth_client.post(f"/api/v1/comicvine/issues/{issue.id}/metadata:refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["refreshed"] is True
    assert body["comicvine_issue_id"] == "3333"


@pytest.mark.asyncio
async def test_apply_correction_stores_canonical_override(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A metadata correction stores the canonical override with provenance."""
    thread = Thread(
        user_id=default_user.id,
        title="Correction Test",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    response = await auth_client.post(
        f"/api/v1/comicvine/issues/{issue.id}/metadata:correct",
        json={
            "field_name": "cover_date",
            "canonical_value": "2026-01-15",
            "reason": "Wrong date on ComicVine",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["corrections"]) == 1
    correction = body["corrections"][0]
    assert correction["field_name"] == "cover_date"
    assert correction["canonical_value"] == "2026-01-15"
    assert correction["provenance"] == "user_correction"


@pytest.mark.asyncio
async def test_list_corrections_only_returns_active(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Only non-reverted corrections appear in the list."""
    thread = Thread(
        user_id=default_user.id,
        title="List Corrections",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    active = IssueMetadataCorrection(
        issue_id=issue.id,
        field_name="name",
        canonical_value="Corrected Name",
        provenance="user_correction",
        created_by=default_user.id,
    )
    reverted = IssueMetadataCorrection(
        issue_id=issue.id,
        field_name="description",
        canonical_value="Old correction",
        provenance="user_correction",
        created_by=default_user.id,
        reverted_at=datetime.now(UTC),
    )
    async_db.add_all([active, reverted])
    await async_db.flush()

    response = await auth_client.get(
        f"/api/v1/comicvine/issues/{issue.id}/metadata:corrections"
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["corrections"]) == 1
    assert body["corrections"][0]["field_name"] == "name"


@pytest.mark.asyncio
async def test_revert_correction_soft_deletes(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Reverting a correction soft-deletes it."""
    thread = Thread(
        user_id=default_user.id,
        title="Revert Test",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    correction = IssueMetadataCorrection(
        issue_id=issue.id,
        field_name="store_date",
        canonical_value="2025-12-01",
        provenance="user_correction",
        created_by=default_user.id,
    )
    async_db.add(correction)
    await async_db.flush()

    response = await auth_client.post(
        f"/api/v1/comicvine/issues/{issue.id}/metadata:revert",
        json={"correction_id": correction.id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["corrections"] == []


@pytest.mark.asyncio
async def test_search_series_without_comicvine_client(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search returns empty results when ComicVine is not configured."""
    monkeypatch.delenv("COMICVINE_API_KEY", raising=False)
    response = await auth_client.get(
        "/api/v1/comicvine/search/series",
        params={"q": "Batman"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "Batman"
    assert body["results"] == []


@pytest.mark.asyncio
async def test_get_series_issues_without_client(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Series issues endpoint returns empty when ComicVine is not configured."""
    monkeypatch.delenv("COMICVINE_API_KEY", raising=False)
    response = await auth_client.get(
        "/api/v1/comicvine/series/12345/issues",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["comicvine_volume_id"] == 12345
    assert body["issues"] == []
