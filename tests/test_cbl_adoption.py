"""Tests for the transactional CBL adoption commit path."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.cbl_adoption import CBLSourceFingerprintResponse
from app.services.cbl_adoption import StalePreviewError, commit_cbl_adoption
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession,
    *,
    user_id: int,
    issue_number: str,
    position: int,
    status: str = "unread",
    read_at: datetime | None = None,
) -> Issue:
    """Create one owned issue plus its owning thread."""
    thread = Thread(
        title="Series",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status=status,
        read_at=read_at,
    )
    async_db.add(issue)
    await async_db.flush()
    return issue


async def _seed_source_list(
    async_db: AsyncSession,
    *,
    issues: list[Issue],
    source_path: str = "Ultimate.cbl",
) -> tuple[int, dict[int, int]]:
    """Persist one CBL source list whose entries map to the issues in order.

    Returns ``(source_list_id, {position: cbl_entry_id})``.
    """
    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="sha-1",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=source_path,
        name="Ultimate Universe",
        declared_issue_count=len(issues),
        content_hash="hash-1",
        revision_sha="sha-1",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    entry_ids: dict[int, int] = {}
    for index, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-{issue.id}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
            )
        )
        await async_db.flush()
        entry = CBLSourceEntry(
            list_id=source_list.id,
            position=index,
            series_name="Series",
            issue_number=issue.issue_number,
            external_issue_identity_id=identity.id,
        )
        async_db.add(entry)
        await async_db.flush()
        entry_ids[index] = entry.id
    return source_list.id, entry_ids


def _fingerprint(source_list_id: int) -> CBLSourceFingerprintResponse:
    """Return the fingerprint matching the seeded source list."""
    return CBLSourceFingerprintResponse(
        source_list_id=source_list_id,
        source_repository="JoshCLWren/CBL-ReadingLists",
        source_path="Ultimate.cbl",
        content_hash="hash-1",
        revision_sha="sha-1",
    )


@pytest.mark.asyncio
async def test_commit_existing_only_creates_no_issues_or_threads(
    async_db: AsyncSession,
) -> None:
    """A reviewed existing-only adoption adds memberships but no issues/threads."""
    user = await get_or_create_user_async(async_db)
    read_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=read_at,
    )
    source_list_id, _ = await _seed_source_list(async_db, issues=[issue])
    issue_count = await async_db.scalar(select(func.count()).select_from(Issue))
    thread_count = await async_db.scalar(select(func.count()).select_from(Thread))

    result = await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={},
        source_fingerprint=_fingerprint(source_list_id),
    )

    assert result["reused_issue_ids"] == [issue.id]
    assert result["created_issue_ids"] == []
    assert result["created_thread_ids"] == []
    assert result["sequence_positions"] == [1]
    assert len(result["membership_ids"]) == 1
    assert result["blocker_refreshed"] is True

    new_issue_count = await async_db.scalar(select(func.count()).select_from(Issue))
    new_thread_count = await async_db.scalar(select(func.count()).select_from(Thread))
    assert new_issue_count == issue_count
    assert new_thread_count == thread_count

    membership = (
        await async_db.execute(
            select(DependencyGroupMembership).where(
                DependencyGroupMembership.issue_id == issue.id
            )
        )
    ).scalar_one()
    assert membership.sequence_order == 1


@pytest.mark.asyncio
async def test_commit_excludes_entry_and_preserves_its_state(
    async_db: AsyncSession,
) -> None:
    """An explicitly excluded existing entry is not adopted and keeps history."""
    user = await get_or_create_user_async(async_db)
    read_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    excluded_issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=read_at,
    )
    source_list_id, entry_ids = await _seed_source_list(
        async_db, issues=[excluded_issue]
    )
    entry_key = str(entry_ids[1])

    result = await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={entry_key: False},
        source_fingerprint=_fingerprint(source_list_id),
    )

    assert result["excluded_positions"] == [1]
    assert result["reused_issue_ids"] == []
    assert result["membership_ids"] == []

    issue = await async_db.get(Issue, excluded_issue.id)
    assert issue is not None
    assert issue.status == "read"
    assert issue.read_at == read_at


@pytest.mark.asyncio
async def test_commit_repeat_is_idempotent(
    async_db: AsyncSession,
) -> None:
    """Repeated identical adoption commits do not duplicate memberships."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
    )
    source_list_id, _ = await _seed_source_list(async_db, issues=[issue])
    fingerprint = _fingerprint(source_list_id)

    first = await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={},
        source_fingerprint=fingerprint,
    )
    second = await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={},
        source_fingerprint=fingerprint,
    )

    membership_count = await async_db.scalar(
        select(func.count())
        .select_from(DependencyGroupMembership)
        .where(DependencyGroupMembership.issue_id == issue.id)
    )
    assert membership_count == 1
    issue_count = await async_db.scalar(select(func.count()).select_from(Issue))
    assert issue_count == 1
    group_count = await async_db.scalar(select(func.count()).select_from(DependencyGroup))
    assert group_count == 1
    assert first["reused_issue_ids"] == second["reused_issue_ids"] == [issue.id]


@pytest.mark.asyncio
async def test_commit_rejects_stale_preview_fingerprint(
    async_db: AsyncSession,
) -> None:
    """A changed source since preview aborts with StalePreviewError."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
    )
    source_list_id, _ = await _seed_source_list(async_db, issues=[issue])
    stale = CBLSourceFingerprintResponse(
        source_list_id=source_list_id,
        source_repository="JoshCLWren/CBL-ReadingLists",
        source_path="Ultimate.cbl",
        content_hash="stale-hash",
        revision_sha="sha-1",
    )

    with pytest.raises(StalePreviewError):
        await commit_cbl_adoption(
            async_db,
            user_id=user.id,
            list_id=source_list_id,
            series_decisions={},
            entry_decisions={},
            source_fingerprint=stale,
        )

    membership_count = await async_db.scalar(
        select(func.count()).select_from(DependencyGroupMembership)
    )
    assert membership_count == 0


@pytest.mark.asyncio
async def test_commit_persists_source_position_gaps(
    async_db: AsyncSession,
) -> None:
    """Exclusions leave position gaps in persisted sequence_order exactly."""
    user = await get_or_create_user_async(async_db)
    excluded = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
    )
    included = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="2",
        position=2,
    )
    source_list_id, entry_ids = await _seed_source_list(
        async_db, issues=[excluded, included]
    )
    included_key = str(entry_ids[2])
    excluded_key = str(entry_ids[1])

    result = await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={included_key: True, excluded_key: False},
        source_fingerprint=_fingerprint(source_list_id),
    )

    assert result["sequence_positions"] == [2]
    assert result["excluded_positions"] == [1]
    membership = (
        await async_db.execute(
            select(DependencyGroupMembership).where(
                DependencyGroupMembership.issue_id == included.id
            )
        )
    ).scalar_one()
    assert membership.sequence_order == 2


@pytest.mark.asyncio
async def test_commit_creates_no_cbl_order_source_dependencies(
    async_db: AsyncSession,
) -> None:
    """Normal adoption persists zero cbl-order:source:* dependency rows."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
    )
    source_list_id, _ = await _seed_source_list(async_db, issues=[issue])

    await commit_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={},
        entry_decisions={},
        source_fingerprint=_fingerprint(source_list_id),
    )

    dep_count = await async_db.scalar(select(func.count()).select_from(Dependency))
    assert dep_count == 0
