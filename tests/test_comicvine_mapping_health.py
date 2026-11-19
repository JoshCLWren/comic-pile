"""Tests for ComicVine mapping health projection in Queue list items.

Covers fully mapped, partial, unresolved, ambiguous/conflicting,
no issue tracking, specials/review-needed, multiple threads in one request,
and user isolation.
"""


import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories import thread_repository
from tests.conftest import get_or_create_user_async


def _identity(external_id: str, metadata: dict | None = None) -> ExternalIdentity:
    return ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.example/issues/{external_id}",
        metadata_json=metadata or {},
    )


@pytest.mark.asyncio
async def test_mapping_health_fully_mapped(
    async_db: AsyncSession,
) -> None:
    """Thread where all issues have confirmed ComicVine mappings."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Fully Mapped Series",
        format="Comic",
        issues_remaining=3,
        total_issues=3,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
        Issue(thread_id=thread.id, issue_number="3", position=3, status="read"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    identities = [
        _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
        _identity("101", {"issue_number": "2", "volume_id": 1, "volume_name": "Series"}),
        _identity("102", {"issue_number": "3", "volume_id": 1, "volume_name": "Series"}),
    ]
    async_db.add_all(identities)
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[0].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=identities[1].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[2].id, external_identity_id=identities[2].id, status="confirmed", confidence=1.0
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 3
    assert health["confirmed_issue_count"] == 3
    assert health["needs_mapping_count"] == 0
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is True


@pytest.mark.asyncio
async def test_mapping_health_partial(
    async_db: AsyncSession,
) -> None:
    """Thread where some issues confirmed, some unresolved."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Partial Mapped Series",
        format="Comic",
        issues_remaining=3,
        total_issues=3,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
        Issue(thread_id=thread.id, issue_number="3", position=3, status="read"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    identities = [
        _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
        _identity("101", {"issue_number": "2", "volume_id": 1, "volume_name": "Series"}),
    ]
    async_db.add_all(identities)
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[0].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=identities[1].id, status="candidate", confidence=0.8
        ),
        # Issue 3 has no mapping
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 3
    assert health["confirmed_issue_count"] == 1
    assert health["needs_mapping_count"] == 2  # 1 candidate + 1 no mapping
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is True


@pytest.mark.asyncio
async def test_mapping_health_unresolved(
    async_db: AsyncSession,
) -> None:
    """Thread where issues exist but none have confirmed mappings."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Unresolved Series",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    identities = [
        _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
    ]
    async_db.add_all(identities)
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[0].id, status="candidate", confidence=0.8
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=identities[0].id, status="unresolved", confidence=None
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 2
    assert health["confirmed_issue_count"] == 0
    assert health["needs_mapping_count"] == 2
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is True


@pytest.mark.asyncio
async def test_mapping_health_needs_review_conflicting(
    async_db: AsyncSession,
) -> None:
    """Thread where an issue has multiple confirmed mappings (conflict)."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Conflicting Series",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    identities = [
        _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
        _identity("101", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
        _identity("102", {"issue_number": "2", "volume_id": 1, "volume_name": "Series"}),
    ]
    async_db.add_all(identities)
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[0].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[1].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=identities[2].id, status="confirmed", confidence=1.0
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 2
    assert health["confirmed_issue_count"] == 2
    assert health["needs_mapping_count"] == 0
    assert health["needs_review_count"] == 1  # Issue 1 has 2 confirmed mappings
    assert health["has_issues"] is True


@pytest.mark.asyncio
async def test_mapping_health_not_applicable_legacy_thread(
    async_db: AsyncSession,
) -> None:
    """Legacy thread without issue tracking returns not_applicable."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Legacy Series",
        format="Comic",
        issues_remaining=5,
        total_issues=None,  # Legacy - no issue tracking
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 0
    assert health["confirmed_issue_count"] == 0
    assert health["needs_mapping_count"] == 0
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is False


@pytest.mark.asyncio
async def test_mapping_health_not_applicable_empty_tracked_thread(
    async_db: AsyncSession,
) -> None:
    """Thread with issue tracking enabled but no issues yet."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Empty Tracked Series",
        format="Comic",
        issues_remaining=0,
        total_issues=10,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 0
    assert health["confirmed_issue_count"] == 0
    assert health["needs_mapping_count"] == 0
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is False


@pytest.mark.asyncio
async def test_mapping_health_multiple_threads_batched(
    async_db: AsyncSession,
) -> None:
    """Multiple threads queried in one batched request."""
    user = await get_or_create_user_async(async_db)

    thread1 = Thread(
        user_id=user.id,
        title="Series One",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
    )
    thread2 = Thread(
        user_id=user.id,
        title="Series Two",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=2,
        status="active",
    )
    thread3 = Thread(
        user_id=user.id,
        title="Legacy Series",
        format="Comic",
        issues_remaining=5,
        total_issues=None,
        queue_position=3,
        status="active",
    )
    async_db.add_all([thread1, thread2, thread3])
    await async_db.flush()

    issues1 = [
        Issue(thread_id=thread1.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread1.id, issue_number="2", position=2, status="read"),
    ]
    issues2 = [
        Issue(thread_id=thread2.id, issue_number="1", position=1, status="unread"),
    ]
    async_db.add_all(issues1 + issues2)
    await async_db.flush()

    id1 = _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series One"})
    id2 = _identity("101", {"issue_number": "2", "volume_id": 1, "volume_name": "Series One"})
    id3 = _identity("102", {"issue_number": "1", "volume_id": 2, "volume_name": "Series Two"})
    async_db.add_all([id1, id2, id3])
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues1[0].id, external_identity_id=id1.id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues1[1].id, external_identity_id=id2.id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues2[0].id, external_identity_id=id3.id, status="candidate", confidence=0.7
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(
        async_db, {thread1.id, thread2.id, thread3.id}
    )

    assert health_map[thread1.id]["tracked_issue_count"] == 2
    assert health_map[thread1.id]["confirmed_issue_count"] == 2
    assert health_map[thread1.id]["needs_mapping_count"] == 0
    assert health_map[thread1.id]["needs_review_count"] == 0

    assert health_map[thread2.id]["tracked_issue_count"] == 1
    assert health_map[thread2.id]["confirmed_issue_count"] == 0
    assert health_map[thread2.id]["needs_mapping_count"] == 1
    assert health_map[thread2.id]["needs_review_count"] == 0

    assert health_map[thread3.id]["tracked_issue_count"] == 0
    assert health_map[thread3.id]["has_issues"] is False


@pytest.mark.asyncio
async def test_mapping_health_user_isolation(
    async_db: AsyncSession,
) -> None:
    """Mapping health only considers issues owned by the thread's user."""
    user1 = await get_or_create_user_async(async_db)
    user2 = User(username="user2_for_isolation")
    async_db.add(user2)
    await async_db.flush()

    thread1 = Thread(
        user_id=user1.id,
        title="User1 Series",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
        status="active",
    )
    thread2 = Thread(
        user_id=user2.id,
        title="User2 Series",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
        status="active",
    )
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    issue1 = Issue(thread_id=thread1.id, issue_number="1", position=1, status="unread")
    issue2 = Issue(thread_id=thread2.id, issue_number="1", position=1, status="unread")
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    identity = _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"})
    async_db.add(identity)
    await async_db.flush()

    # Only user1's issue gets a confirmed mapping
    mapping = IssueExternalIdentityMapping(
        issue_id=issue1.id, external_identity_id=identity.id, status="confirmed", confidence=1.0
    )
    async_db.add(mapping)
    await async_db.commit()

    # Query both threads - each should only see their own issues' mappings
    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread1.id, thread2.id})

    assert health_map[thread1.id]["confirmed_issue_count"] == 1
    assert health_map[thread2.id]["confirmed_issue_count"] == 0
    assert health_map[thread2.id]["needs_mapping_count"] == 1


@pytest.mark.asyncio
async def test_mapping_health_special_issue_needs_review(
    async_db: AsyncSession,
) -> None:
    """Special issues (annuals, one-shots) with candidate status flagged for review."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Series With Specials",
        format="Comic",
        issues_remaining=3,
        total_issues=3,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="read"),
        Issue(thread_id=thread.id, issue_number="Annual 1", position=2, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=3, status="unread"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    identities = [
        _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"}),
        _identity("101", {"issue_number": "Annual 1", "volume_id": 1, "volume_name": "Series"}),
        _identity("102", {"issue_number": "2", "volume_id": 1, "volume_name": "Series"}),
    ]
    async_db.add_all(identities)
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=identities[0].id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=identities[1].id, status="candidate", confidence=0.6
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[2].id, external_identity_id=identities[2].id, status="confirmed", confidence=1.0
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    assert health["tracked_issue_count"] == 3
    assert health["confirmed_issue_count"] == 2
    assert health["needs_mapping_count"] == 1  # The annual with candidate status
    assert health["needs_review_count"] == 0
    assert health["has_issues"] is True


@pytest.mark.asyncio
async def test_mapping_health_empty_input(
    async_db: AsyncSession,
) -> None:
    """Empty thread_ids set returns empty mapping."""
    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, set())
    assert health_map == {}


@pytest.mark.asyncio
async def test_mapping_health_non_comicvine_provider_ignored(
    async_db: AsyncSession,
) -> None:
    """Mappings from non-ComicVine providers are ignored."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        user_id=user.id,
        title="Mixed Provider Series",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
    )
    async_db.add(thread)
    await async_db.flush()

    issues = [
        Issue(thread_id=thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="2", position=2, status="unread"),
    ]
    async_db.add_all(issues)
    await async_db.flush()

    cv_identity = _identity("100", {"issue_number": "1", "volume_id": 1, "volume_name": "Series"})
    other_identity = ExternalIdentity(
        provider="marvel",
        entity_type="issue",
        external_id="200",
        external_url="https://marvel.example/issues/200",
        metadata_json={"issue_number": "2", "volume_id": 2, "volume_name": "Other Series"},
    )
    async_db.add_all([cv_identity, other_identity])
    await async_db.flush()

    mappings = [
        IssueExternalIdentityMapping(
            issue_id=issues[0].id, external_identity_id=cv_identity.id, status="confirmed", confidence=1.0
        ),
        IssueExternalIdentityMapping(
            issue_id=issues[1].id, external_identity_id=other_identity.id, status="confirmed", confidence=1.0
        ),
    ]
    async_db.add_all(mappings)
    await async_db.commit()

    health_map = await thread_repository.fetch_comicvine_mapping_health(async_db, {thread.id})
    health = health_map[thread.id]

    # Only ComicVine mappings count
    assert health["tracked_issue_count"] == 2
    assert health["confirmed_issue_count"] == 1  # Only issue 1 has ComicVine confirmed
    assert health["needs_mapping_count"] == 1  # Issue 2 has no ComicVine mapping
    assert health["needs_review_count"] == 0
