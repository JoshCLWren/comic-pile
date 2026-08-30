"""API coverage for issue-scoped ComicVine intelligence."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services import comicvine_intelligence


def _identity(external_id: str, metadata: dict[str, object]) -> ExternalIdentity:
    return ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.example/issues/{external_id}",
        metadata_json=metadata,
    )


@pytest.mark.asyncio
async def test_comicvine_intelligence_normalizes_metadata_and_matches_arc_members(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rich metadata includes mapped duplicates and missing external arc members."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    primary_thread = Thread(
        user_id=default_user.id,
        title="Alpha",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    duplicate_thread = Thread(
        user_id=default_user.id,
        title="Alpha Collection",
        format="trade",
        issues_remaining=1,
        total_issues=1,
        queue_position=2,
    )
    async_db.add_all([primary_thread, duplicate_thread])
    await async_db.flush()
    current = Issue(thread_id=primary_thread.id, issue_number="1", position=1, status="unread")
    related = Issue(thread_id=primary_thread.id, issue_number="2", position=2, status="read")
    duplicate = Issue(
        thread_id=duplicate_thread.id,
        issue_number="Chapter 2",
        position=1,
        status="unread",
    )
    async_db.add_all([current, related, duplicate])
    await async_db.flush()

    arc = [{"id": 42, "name": "The Big Arc", "site_detail_url": "https://arc.example"}]
    current_identity = _identity(
        "100",
        {
            "name": "Opening",
            "issue_number": "1",
            "volume_id": 8,
            "volume_name": "Alpha",
            "description": "<p>A <strong>bold</strong> beginning.</p>",
            "image_url": "https://images.example/100.jpg",
            "cover_date": "2026-01-01",
            "store_date": "2025-12-20",
            "person_credits": [{"name": "Writer One", "role": "writer, cover"}],
            "story_arc_credits": arc,
        },
    )
    related_identity = _identity(
        "101",
        {
            "name": "Middle",
            "issue_number": "2",
            "volume_id": 8,
            "volume_name": "Alpha",
            "cover_date": "2026-02-01",
            "story_arc_credits": arc,
        },
    )
    missing_identity = _identity(
        "102",
        {
            "name": "Finale",
            "issue_number": "1",
            "volume_id": 9,
            "volume_name": "Beta Special",
            "cover_date": "2026-03-01",
            "story_arc_credits": arc,
        },
    )
    async_db.add_all([current_identity, related_identity, missing_identity])
    await async_db.flush()
    async_db.add_all(
        [
            IssueExternalIdentityMapping(
                issue_id=current.id,
                external_identity_id=current_identity.id,
                status="confirmed",
                confidence=1,
            ),
            IssueExternalIdentityMapping(
                issue_id=related.id,
                external_identity_id=related_identity.id,
                status="confirmed",
                confidence=1,
            ),
            IssueExternalIdentityMapping(
                issue_id=duplicate.id,
                external_identity_id=related_identity.id,
                status="confirmed",
                confidence=1,
            ),
        ]
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{current.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "A bold beginning."
    assert body["image_url"] == "https://images.example/100.jpg"
    assert body["creators"] == [
        {"creator_id": None, "name": "Writer One", "roles": ["writer", "cover"]}
    ]
    related_issues = body["story_arcs"][0]["related_issues"]
    assert [item["comicvine_issue_id"] for item in related_issues] == ["101", "102"]
    assert [item["name"] for item in related_issues] == ["Middle", "Finale"]
    assert len(related_issues[0]["comicpile_matches"]) == 2
    assert {match["status"] for match in related_issues[0]["comicpile_matches"]} == {
        "read",
        "unread",
    }
    assert related_issues[1]["comicpile_matches"] == []


@pytest.mark.asyncio
async def test_comicvine_intelligence_absence_and_ownership(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """An owned unmapped issue is null while another user's issue remains hidden."""
    other_user = User(username="comicvine_other_owner")
    owned_thread = Thread(
        user_id=default_user.id,
        title="Owned",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=10,
    )
    other_thread = Thread(
        user=other_user,
        title="Hidden",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add_all([other_user, owned_thread, other_thread])
    await async_db.flush()
    owned = Issue(thread_id=owned_thread.id, issue_number="1", position=1, status="unread")
    hidden = Issue(thread_id=other_thread.id, issue_number="1", position=1, status="unread")
    async_db.add_all([owned, hidden])
    await async_db.flush()

    absent = await auth_client.get(f"/api/v1/issues/{owned.id}/comicvine")
    forbidden = await auth_client.get(f"/api/v1/issues/{hidden.id}/comicvine")

    assert absent.status_code == 200
    assert absent.json() is None
    assert forbidden.status_code == 404


@pytest.mark.asyncio
async def test_comicvine_intelligence_stays_usable_when_hydration_scheduling_fails(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider/scheduling failure never breaks the issue-view or rating workflow."""
    thread = Thread(
        user_id=default_user.id,
        title="Resilient series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=5,
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="555",
        metadata_json={"issue_number": "1", "name": "Partial"},
        updated_at=datetime.now(UTC),
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

    async def _boom(_identity_id: int) -> bool:
        raise TimeoutError("simulated advisory-lock timeout")

    monkeypatch.setattr(
        comicvine_intelligence,
        "refresh_issue_metadata",
        _boom,
    )

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["comicvine_issue_id"] == "555"
    assert body["name"] == "Partial"


@pytest.mark.asyncio
async def test_comicvine_creator_stable_id_propagation(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creator credits with stable provider IDs expose creator_id in the API response."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Creator ID Test",
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
        "200",
        {
            "name": "Test Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 12345, "name": "Alan Moore", "role": "writer"},
                {"id": 67890, "name": "Frank Miller", "role": "artist"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 2
    by_name = {c["name"]: c for c in creators}
    assert by_name["Alan Moore"]["creator_id"] == 12345
    assert by_name["Frank Miller"]["creator_id"] == 67890


@pytest.mark.asyncio
async def test_comicvine_creator_same_name_different_id_distinct(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two creators with the same display name but different IDs remain distinct."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Same Name Test",
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
        "300",
        {
            "name": "Same Name Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 100, "name": "John Smith", "role": "writer"},
                {"id": 200, "name": "John Smith", "role": "artist"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 2
    ids = [c["creator_id"] for c in creators]
    assert ids == [100, 200]


@pytest.mark.asyncio
async def test_comicvine_creator_multi_role_grouping(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One creator credited in multiple roles on the same issue is grouped into one identity."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Multi-Role Test",
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
        "400",
        {
            "name": "Multi-Role Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 42, "name": "Grant Morrison", "role": "writer"},
                {"id": 42, "name": "Grant Morrison", "role": "cover"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 1
    creator = creators[0]
    assert creator["creator_id"] == 42
    assert creator["name"] == "Grant Morrison"
    assert sorted(creator["roles"]) == ["cover", "writer"]


@pytest.mark.asyncio
async def test_comicvine_creator_duplicate_credits_deduplicated(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duplicate provider credit rows for the same person/role do not duplicate identities."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Duplicate Credits Test",
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
        "500",
        {
            "name": "Duplicate Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 99, "name": "Duplicate Person", "role": "writer"},
                {"id": 99, "name": "Duplicate Person", "role": "writer"},
                {"id": 99, "name": "Duplicate Person", "role": "writer"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 1
    assert creators[0]["creator_id"] == 99
    assert creators[0]["roles"] == ["writer"]


@pytest.mark.asyncio
async def test_comicvine_creator_missing_id_not_fabricated(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credits without a usable stable ID produce creator_id=None, not a fabricated key."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Missing ID Test",
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
        "600",
        {
            "name": "Missing ID Issue",
            "issue_number": "1",
            "person_credits": [
                {"name": "No ID Creator", "role": "writer"},
                {"id": 42, "name": "Has ID Creator", "role": "artist"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 2
    by_name = {c["name"]: c for c in creators}
    assert by_name["No ID Creator"]["creator_id"] is None
    assert by_name["Has ID Creator"]["creator_id"] == 42
    assert by_name["No ID Creator"]["roles"] == ["writer"]


@pytest.mark.asyncio
async def test_comicvine_creator_comma_separated_roles_split_and_grouped(
    auth_client,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Comma-separated role strings are split into individual roles and grouped."""

    async def _noop_refresh(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(comicvine_intelligence, "refresh_issue_metadata", _noop_refresh)

    thread = Thread(
        user_id=default_user.id,
        title="Comma Roles Test",
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
        "700",
        {
            "name": "Comma Roles Issue",
            "issue_number": "1",
            "person_credits": [
                {"id": 55, "name": "Multi Role Person", "role": "writer, cover, editor"},
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
            confidence=1,
        )
    )
    await async_db.flush()

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    creators = body["creators"]
    assert len(creators) == 1
    creator = creators[0]
    assert creator["creator_id"] == 55
    assert creator["name"] == "Multi Role Person"
    assert sorted(creator["roles"]) == ["cover", "editor", "writer"]
