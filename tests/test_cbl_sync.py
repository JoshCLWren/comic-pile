"""Persistence tests for normalized CBL mirror synchronization."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cbl_ingest import CBLBook, CBLList
from app.cbl_sync import sync_cbl_lists
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity


def _book(
    position: int,
    *,
    issue_number: str,
    comicvine_series_id: str | None = None,
    comicvine_issue_id: str | None = None,
) -> CBLBook:
    """Build a compact CBL book fixture."""
    return CBLBook(
        position=position,
        series="X-Men",
        issue_number=issue_number,
        volume_year=1991,
        publication_year=1992,
        comicvine_series_id=comicvine_series_id,
        comicvine_issue_id=comicvine_issue_id,
    )


def _list(*, content_hash: str = "hash-v1", books: tuple[CBLBook, ...] | None = None) -> CBLList:
    """Build one parsed CBL list fixture."""
    selected_books = books or (
        _book(
            1,
            issue_number="1",
            comicvine_series_id="4050-4605",
            comicvine_issue_id="4000-34308",
        ),
        _book(2, issue_number="2", comicvine_issue_id="4000-34309"),
    )
    return CBLList(
        source_path="Marvel/Events/X-Men Test.cbl",
        content_hash=content_hash,
        name="X-Men Test",
        declared_issue_count=len(selected_books),
        books=selected_books,
    )


@pytest.mark.asyncio
async def test_cbl_sync_is_idempotent_and_retains_comicvine_identity_evidence(
    async_db: AsyncSession,
) -> None:
    """Unchanged files write once while embedded provider IDs remain normalized."""
    synced_at = datetime(2026, 8, 11, 1, 40, tzinfo=UTC)
    first = await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="abc123",
        parsed_lists=(_list(),),
        synced_at=synced_at,
    )
    second = await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="abc123",
        parsed_lists=(_list(),),
        synced_at=synced_at,
    )

    assert first.source_created is True
    assert first.inserted_lists == 1
    assert first.entries_written == 2
    assert second.source_created is False
    assert second.inserted_lists == 0
    assert second.updated_lists == 0
    assert second.deactivated_lists == 0
    assert second.unchanged_lists == 1
    assert second.entries_written == 0

    assert await async_db.scalar(select(func.count()).select_from(CBLSource)) == 1
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceList)) == 1
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)) == 2
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 3

    stored = await async_db.scalar(select(CBLSourceList))
    assert stored is not None
    assert stored.source_path == "Marvel/Events/X-Men Test.cbl"
    assert stored.revision_sha == "abc123"
    assert stored.active is True


@pytest.mark.asyncio
async def test_cbl_sync_replaces_changed_entries_and_marks_removed_lists_inactive(
    async_db: AsyncSession,
) -> None:
    """Changed files replace entries transactionally and removed files remain historical."""
    await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="abc123",
        parsed_lists=(_list(),),
    )
    changed = _list(
        content_hash="hash-v2",
        books=(_book(1, issue_number="3", comicvine_issue_id="4000-34310"),),
    )
    update_summary = await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="def456",
        parsed_lists=(changed,),
    )

    assert update_summary.updated_lists == 1
    assert update_summary.entries_written == 1
    entries = list((await async_db.execute(select(CBLSourceEntry))).scalars().all())
    assert [(entry.position, entry.issue_number) for entry in entries] == [(1, "3")]

    remove_summary = await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="ghi789",
        parsed_lists=(),
    )
    stored = await async_db.scalar(select(CBLSourceList))

    assert remove_summary.deactivated_lists == 1
    assert stored is not None
    assert stored.active is False
    assert stored.revision_sha == "ghi789"
    assert stored.source_path == "Marvel/Events/X-Men Test.cbl"


@pytest.mark.asyncio
async def test_cbl_sync_dry_run_reports_without_writes(async_db: AsyncSession) -> None:
    """Dry-run mode returns machine-readable intent without touching persistence."""
    summary = await sync_cbl_lists(
        async_db,
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="abc123",
        parsed_lists=(_list(),),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.source_created is True
    assert summary.inserted_lists == 1
    assert summary.entries_written == 2
    assert await async_db.scalar(select(func.count()).select_from(CBLSource)) == 0
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceList)) == 0
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)) == 0
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 0
