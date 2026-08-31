"""Tests for CBL source reconciliation and the crossover rebuild repair path."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.cbl_reconciliation import reconcile_cbl_source_list
from scripts.rebuild_crossover_from_cbl import _member_issue_ids, _rebuild
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession,
    *,
    user_id: int,
    issue_number: str,
    position: int,
    status: str = "unread",
    read_at: datetime | None = None,
    thread_title: str = "Series",
) -> Issue:
    """Create one owned issue plus its owning thread."""
    thread = Thread(
        title=thread_title,
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
    issues_by_position: dict[int, str] | None = None,
    series_names: dict[int, str] | None = None,
    source_path: str = "Ultimate.cbl",
    omit_identity_at: set[int] | None = None,
) -> int:
    """Persist one CBL source list whose entries map to given issues in order."""
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

    for index, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-{issue.id}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        if index not in (omit_identity_at or set()):
            async_db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                )
            )
            await async_db.flush()
        async_db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=index,
                series_name=(series_names or {}).get(index, "Series"),
                issue_number=(issues_by_position or {}).get(
                    index, issue.issue_number
                ),
                external_issue_identity_id=identity.id,
            )
        )
        await async_db.flush()
    return source_list.id


async def _make_group(
    async_db: AsyncSession,
    *,
    user_id: int,
    name: str = "Ultimate Universe",
    issue_ids: tuple[int, ...] = (),
) -> DependencyGroup:
    """Create one dependency group with optional issue members."""
    group = DependencyGroup(user_id=user_id, name=name)
    async_db.add(group)
    await async_db.flush()
    for issue_id in issue_ids:
        async_db.add(
            DependencyGroupMembership(group_id=group.id, issue_id=issue_id)
        )
    await async_db.flush()
    return group


@pytest.mark.asyncio
async def test_reconcile_preserves_full_source_order_including_read_entries(
    async_db: AsyncSession,
) -> None:
    """Read and unread source entries remain position-for-position ordered."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    issues = [
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=now,
        ),
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="2",
            position=1,
            status="read",
            read_at=now,
        ),
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="3",
            position=1,
        ),
    ]
    source_list_id = await _seed_source_list(async_db, issues=issues)

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list_id,
        user_id=user.id,
    )

    assert report.total_positions == 3
    assert [entry["cbl_position"] for entry in report.entries] == [1, 2, 3]
    assert [entry["resolved_issue_id"] for entry in report.entries] == [
        issue.id for issue in issues
    ]
    assert [entry["read_status"] for entry in report.entries] == [
        "read",
        "read",
        "unread",
    ]
    assert report.first_unread_position == 3
    assert report.first_unread_issue_id == issues[2].id
    assert report.first_unread_entry is not None
    assert report.first_unread_entry["resolved_issue_id"] == issues[2].id
    assert report.missing_source_entries == ()
    assert report.extra_member_issue_ids == ()
    assert report.ambiguous_mappings == ()
    assert report.source_list_id == source_list_id
    assert report.source_path == "Ultimate.cbl"


@pytest.mark.asyncio
async def test_reconcile_surfaces_unresolved_and_extra_members(
    async_db: AsyncSession,
) -> None:
    """Unresolved entries and baseline extras are never silently dropped."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db, user_id=user.id, issue_number="1", position=1
    )
    source_list_id = await _seed_source_list(
        async_db,
        issues=[issue],
        omit_identity_at={1},
    )

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list_id,
        user_id=user.id,
        baseline_member_issue_ids=(issue.id, 9999),
    )

    assert report.entries[0]["resolved_issue_id"] is None
    assert report.entries[0]["resolution_status"] in (
        "comicvine_identity_not_known",
        "ambiguous_no_comicvine_id",
        "no_owned_issue_for_comicvine_id",
        "unresolved",
    )
    assert report.unresolved_count == 1
    assert report.extra_member_issue_ids == (issue.id, 9999)


@pytest.mark.asyncio
async def test_reconcile_detects_duplicate_canonical_identity(
    async_db: AsyncSession,
) -> None:
    """Two owner issues on one ComicVine identity are reported as duplicate."""
    user = await get_or_create_user_async(async_db)
    first = await _make_issue(
        async_db, user_id=user.id, issue_number="1", position=1
    )
    second = await _make_issue(
        async_db, user_id=user.id, issue_number="2", position=1
    )

    source = CBLSource(
        repository="repo/events",
        revision_sha="sha-1",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Dup.cbl",
        name="Dup",
        declared_issue_count=1,
        content_hash="hash-1",
        revision_sha="sha-1",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-same",
        metadata_json={},
    )
    async_db.add(identity)
    await async_db.flush()
    for issue in (first, second):
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
            )
        )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Series",
            issue_number="1",
            external_issue_identity_id=identity.id,
        )
    )
    await async_db.flush()

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list.id,
        user_id=user.id,
    )

    assert report.entries[0]["is_duplicate_identity"] is True
    assert report.duplicate_identity_groups >= 1
    assert report.entries[0]["resolved_issue_id"] is not None


@pytest.mark.asyncio
async def test_reconcile_rejects_missing_source_list(
    async_db: AsyncSession,
) -> None:
    """A missing source list is rejected instead of reconciled as empty."""
    user = await get_or_create_user_async(async_db)
    for kwargs in ({"source_list_id": 999999}, {"list_id": 999999}):
        with pytest.raises(ValueError):
            await reconcile_cbl_source_list(
                async_db,
                user_id=user.id,
                **kwargs,
            )


@pytest.mark.asyncio
async def test_repair_rebuilds_membership_preserving_source_order(
    async_db: AsyncSession,
) -> None:
    """The rebuild restores every resolved entry with authoritative positions."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    read = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=now,
    )
    unread = await _make_issue(
        async_db, user_id=user.id, issue_number="2", position=1
    )
    not_in_source = await _make_issue(
        async_db, user_id=user.id, issue_number="3", position=1
    )
    source_list_id = await _seed_source_list(async_db, issues=[read, unread])
    group = await _make_group(
        async_db,
        user_id=user.id,
        issue_ids=(not_in_source.id, read.id),
    )

    args = argparse.Namespace(
        source_list_id=source_list_id,
        group_id=group.id,
        user_id=user.id,
        commit=True,
    )
    payload = await _rebuild(async_db, args)

    assert payload["entries_resolved"] == 2
    assert set(await _member_issue_ids(async_db, group.id)) == {
        read.id,
        unread.id,
    }
    assert payload["members_removed_extra"] == [not_in_source.id]
    assert payload["first_unread_issue_id"] == unread.id
    stored_unread = await async_db.get(Issue, unread.id)
    assert stored_unread is not None and stored_unread.status == "unread"

    rows = (
        await async_db.execute(
            select(DependencyGroupMembership).where(
                DependencyGroupMembership.group_id == group.id
            )
        )
    ).scalars().all()
    order_map = {row.issue_id: row.sequence_order for row in rows}
    assert order_map[read.id] == 1
    assert order_map[unread.id] == 2


@pytest.mark.asyncio
async def test_repair_dry_run_does_not_mutate(
    async_db: AsyncSession,
) -> None:
    """Dry-run reports without changing crossover membership."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(
        async_db, user_id=user.id, issue_number="1", position=1
    )
    source_list_id = await _seed_source_list(async_db, issues=[issue])
    group = await _make_group(async_db, user_id=user.id)

    args = argparse.Namespace(
        source_list_id=source_list_id,
        group_id=group.id,
        user_id=user.id,
        commit=False,
    )
    payload = await _rebuild(async_db, args)

    assert payload["dry_run"] is True
    assert payload["members_for_group_before"] == []
    assert await _member_issue_ids(async_db, group.id) == []
