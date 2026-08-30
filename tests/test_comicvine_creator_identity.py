"""Tests for stable creator identity plumbing through ComicVine issue intelligence."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services import comicvine_intelligence
from app.services.comicvine_intelligence import _creators


# ---------------------------------------------------------------------------
# Unit tests for _creators()
# ---------------------------------------------------------------------------


class TestCreatorsUnit:
    """Unit tests for the _creators normalization function."""

    def test_stable_creator_key_from_provider_id(self) -> None:
        """Credits with an ID emit a canonical comicvine:<id> creator_key."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 42, "name": "Stan Lee", "role": "writer"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert result[0].creator_key == "comicvine:42"
        assert result[0].name == "Stan Lee"
        assert result[0].roles == ["writer"]

    def test_same_name_different_id_creators_are_distinguishable(self) -> None:
        """Two creators named 'John Smith' with different IDs remain separate."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 100, "name": "John Smith", "role": "writer"},
                {"id": 200, "name": "John Smith", "role": "penciler"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 2
        keys = {c.creator_key for c in result}
        assert keys == {"comicvine:100", "comicvine:200"}
        by_key = {c.creator_key: c for c in result}
        assert by_key["comicvine:100"].roles == ["writer"]
        assert by_key["comicvine:200"].roles == ["penciler"]

    def test_multiple_roles_for_one_creator_are_grouped(self) -> None:
        """Multiple credit rows for the same person merge into one creator."""
        metadata: dict[str, object] = {
            "creator_credits": [
                {"id": 7, "name": "Frank Miller", "role": "writer"},
                {"id": 7, "name": "Frank Miller", "role": "penciler"},
                {"id": 7, "name": "Frank Miller", "role": "inker"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert result[0].creator_key == "comicvine:7"
        assert result[0].name == "Frank Miller"
        assert set(result[0].roles) == {"writer", "penciler", "inker"}

    def test_duplicate_credits_do_not_duplicate_roles(self) -> None:
        """Exact duplicate credit rows (same ID + same role) collapse cleanly."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 5, "name": "Alan Moore", "role": "writer"},
                {"id": 5, "name": "Alan Moore", "role": "writer"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert result[0].roles == ["writer"]
        assert result[0].creator_key == "comicvine:5"

    def test_comma_separated_roles_are_split(self) -> None:
        """A single role string with commas is split into multiple roles."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 3, "name": "Writer One", "role": "writer, cover"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert result[0].roles == ["writer", "cover"]
        assert result[0].creator_key == "comicvine:3"

    def test_missing_id_yields_null_creator_key(self) -> None:
        """Credits without a stable ID produce creator_key=None (not fabricated)."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Anonymous Artist", "role": "penciler"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert result[0].creator_key is None
        assert result[0].name == "Anonymous Artist"
        assert result[0].roles == ["penciler"]

    def test_empty_name_credits_are_skipped(self) -> None:
        """Credits with no usable name are silently dropped."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 99, "name": "", "role": "writer"},
                {"id": 100, "role": "artist"},
                {"name": "  ", "role": "inker"},
            ],
        }
        result = _creators(metadata)
        assert result == []

    def test_no_credits_returns_empty_list(self) -> None:
        """Missing credit keys return an empty list."""
        assert _creators({}) == []
        assert _creators({"person_credits": []}) == []
        assert _creators({"creator_credits": []}) == []

    def test_preserves_credits_without_id_separate_from_grouped(self) -> None:
        """ID-based and name-only credits coexist in correct order."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 10, "name": "Known Creator", "role": "writer"},
                {"name": "Unknown Creator", "role": "artist"},
                {"id": 20, "name": "Another Known", "role": "inker"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 3
        assert result[0].creator_key == "comicvine:10"
        assert result[1].creator_key is None
        assert result[2].creator_key == "comicvine:20"

    def test_multi_role_dedup_merges_roles_correctly(self) -> None:
        """Same creator with overlapping roles across credits merges without duplication."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"id": 1, "name": "Jim Lee", "role": "penciler, inker"},
                {"id": 1, "name": "Jim Lee", "role": "cover"},
            ],
        }
        result = _creators(metadata)
        assert len(result) == 1
        assert set(result[0].roles) == {"penciler", "inker", "cover"}
        assert result[0].creator_key == "comicvine:1"


# ---------------------------------------------------------------------------
# API-level integration tests for creator identity
# ---------------------------------------------------------------------------


def _identity(external_id: str, metadata: dict[str, object]) -> ExternalIdentity:
    return ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.example/issues/{external_id}",
        metadata_json=metadata,
    )


@pytest.mark.asyncio
async def test_intelligence_exposes_stable_creator_key_when_id_present(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API returns creator_key when provider metadata supplies a stable ID."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Test Issue",
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
    identity = _identity(
        "9001",
        {
            "name": "Test Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 42, "name": "Stan Lee", "role": "writer"},
                {"id": 43, "name": "Jack Kirby", "role": "penciler"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 2
    by_key = {c["creator_key"]: c for c in creators}
    assert "comicvine:42" in by_key
    assert "comicvine:43" in by_key
    assert by_key["comicvine:42"]["name"] == "Stan Lee"
    assert by_key["comicvine:43"]["name"] == "Jack Kirby"


@pytest.mark.asyncio
async def test_intelligence_creator_key_is_stable_not_name_based(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creator keys use provider ID, not display name, so same-name creators differ."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Name Collision",
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
    identity = _identity(
        "9002",
        {
            "name": "Name Collision Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 100, "name": "John Smith", "role": "writer"},
                {"id": 200, "name": "John Smith", "role": "penciler"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    creators = response.json()["creators"]
    keys = {c["creator_key"] for c in creators}
    assert keys == {"comicvine:100", "comicvine:200"}
    assert len(creators) == 2


@pytest.mark.asyncio
async def test_intelligence_groups_multi_role_creator_under_one_identity(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple credit rows for the same creator merge into one creator entry."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Multi-Role Issue",
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
    identity = _identity(
        "9003",
        {
            "name": "Multi-Role Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 7, "name": "Frank Miller", "role": "writer"},
                {"id": 7, "name": "Frank Miller", "role": "penciler"},
                {"id": 7, "name": "Frank Miller", "role": "cover"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    creators = response.json()["creators"]
    assert len(creators) == 1
    assert creators[0]["creator_key"] == "comicvine:7"
    assert set(creators[0]["roles"]) == {"writer", "penciler", "cover"}


@pytest.mark.asyncio
async def test_intelligence_deduplicates_exact_duplicate_credits(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact duplicate credit rows do not produce duplicate creators."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Dupes",
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
    identity = _identity(
        "9004",
        {
            "name": "Dupes Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 5, "name": "Alan Moore", "role": "writer"},
                {"id": 5, "name": "Alan Moore", "role": "writer"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    creators = response.json()["creators"]
    assert len(creators) == 1
    assert creators[0]["creator_key"] == "comicvine:5"
    assert creators[0]["roles"] == ["writer"]


@pytest.mark.asyncio
async def test_intelligence_missing_creator_ids_do_not_fabricate_keys(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credits without stable IDs produce creator_key=null, not name-derived keys."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="No IDs",
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
    identity = _identity(
        "9005",
        {
            "name": "No ID Issue",
            "issue_number": "1",
            "person_credits": [
                {"name": "Anonymous Writer", "role": "writer"},
                {"name": "Anonymous Artist", "role": "penciler"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    creators = response.json()["creators"]
    assert len(creators) == 2
    for creator in creators:
        assert creator["creator_key"] is None
    names = {c["name"] for c in creators}
    assert names == {"Anonymous Writer", "Anonymous Artist"}


@pytest.mark.asyncio
async def test_intelligence_mixed_id_and_no_id_credits(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mix of ID-bearing and ID-less credits coexist correctly."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Mixed",
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
    identity = _identity(
        "9006",
        {
            "name": "Mixed Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 10, "name": "Known Creator", "role": "writer"},
                {"name": "Unknown Creator", "role": "artist"},
                {"id": 20, "name": "Another Known", "role": "inker"},
            ],
        },
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

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    creators = response.json()["creators"]
    assert len(creators) == 3
    by_key_or_name = {}
    for c in creators:
        key = c["creator_key"] or c["name"]
        by_key_or_name[key] = c
    assert by_key_or_name["comicvine:10"]["name"] == "Known Creator"
    assert by_key_or_name["Unknown Creator"]["creator_key"] is None
    assert by_key_or_name["comicvine:20"]["name"] == "Another Known"
