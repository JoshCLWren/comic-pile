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
) -> None:
    """Rich metadata includes mapped duplicates and missing external arc members."""
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
    assert body["creators"] == [{"name": "Writer One", "roles": ["writer", "cover"]}]
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

    def _boom(_identity_id: int) -> bool:
        raise RuntimeError("simulated event-loop failure")

    monkeypatch.setattr(
        comicvine_intelligence,
        "schedule_issue_metadata_hydration",
        _boom,
    )

    response = await auth_client.get(f"/api/v1/issues/{issue.id}/comicvine")

    assert response.status_code == 200
    body = response.json()
    assert body is not None
    assert body["comicvine_issue_id"] == "555"
    assert body["name"] == "Partial"
