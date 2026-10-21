"""Full-fork CBL inventory and repeatable mirror-refresh coverage."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from types import TracebackType
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.cbl_ingest import build_cbl_inventory, parse_cbl_mirror
from app.cbl_sync import CBLSyncSummary, sync_cbl_lists
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import ExternalIdentity
from scripts import sync_cbl_mirror

REPOSITORY = "JoshCLWren/CBL-ReadingLists"

EVENT_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>Event</Name>
  <NumIssues>2</NumIssues>
  <Books>
    <Book Series="Event" Number="1" Volume="2020" Year="2020" SeriesID="100" IssueID="1000" />
    <Book Series="Event" Number="2" Volume="2020" Year="2020" SeriesID="100" IssueID="1001" />
  </Books>
</ReadingList>
"""

HERO_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>Hero</Name>
  <NumIssues>1</NumIssues>
  <Books>
    <Book Series="Hero" Number="1" Volume="2010" Year="2010" SeriesID="200" />
  </Books>
</ReadingList>
"""

CHANGED_HERO_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>Hero</Name>
  <NumIssues>1</NumIssues>
  <Books>
    <Book Series="Hero" Number="2" Volume="2010" Year="2011" SeriesID="200" IssueID="2001" />
  </Books>
</ReadingList>
"""

DUPLICATE_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>Duplicate</Name>
  <NumIssues>1</NumIssues>
  <Books>
    <Book Series="Other" Number="1" Volume="2005" Year="2005" SeriesID="300" IssueID="3000" />
  </Books>
</ReadingList>
"""

ROOT_CBL = """<?xml version="1.0"?>
<ReadingList>
  <Name>Root</Name>
  <NumIssues>1</NumIssues>
  <Books>
    <Book Series="Root" Number="1" Volume="1999" Year="1999" SeriesID="400" IssueID="4000" />
  </Books>
</ReadingList>
"""


def _write(path: Path, content: str) -> None:
    """Write one fixture CBL file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_initial_mirror(root: Path) -> None:
    """Create a publisher/nested mirror with unchanged, duplicate, and removable files."""
    _write(root / "Marvel" / "Events" / "event.cbl", EVENT_CBL)
    _write(root / "DC" / "Characters" / "unsorted" / "hero.cbl", HERO_CBL)
    _write(root / "Other" / "unsorted" / "duplicate-a.cbl", DUPLICATE_CBL)
    _write(root / "Other" / "unsorted" / "duplicate-b.cbl", DUPLICATE_CBL)
    _write(root / "Marvel" / "Broken" / "bad.cbl", ROOT_CBL)
    _write(root / "root.cbl", ROOT_CBL)


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()


def _inventory_args(
    root: Path, *, inventory_only: bool, dry_run: bool = False
) -> argparse.Namespace:
    """Build CLI arguments for an inventory or dry-run invocation."""
    return argparse.Namespace(
        mirror_path=root,
        repository=REPOSITORY,
        revision_sha="abc123",
        dry_run=dry_run,
        inventory_only=inventory_only,
    )


def test_full_fork_inventory_reports_exact_path_hash_and_comicvine_counts(
    tmp_path: Path,
) -> None:
    """Every discovered file contributes exact aggregate and per-path counts."""
    _write_initial_mirror(tmp_path)
    (tmp_path / "Marvel" / "Broken" / "bad.cbl").write_text("<ReadingList><Books>")

    parsed, failures = parse_cbl_mirror(tmp_path)
    inventory = build_cbl_inventory(parsed, failures)

    assert inventory.total_files == 6
    assert inventory.parsed_files == 5
    assert inventory.failed_files == 1
    assert inventory.total_entries == 6
    assert inventory.entries_with_comicvine_series_id == 6
    assert inventory.entries_with_comicvine_issue_id == 5
    assert inventory.entries_with_comicvine_pair == 5
    assert inventory.distinct_comicvine_series_ids == 4
    assert inventory.distinct_comicvine_issue_ids == 4
    assert inventory.duplicate_content_hash_groups == 1
    assert inventory.duplicate_source_paths == 0
    assert inventory.declared_count_mismatches == 0

    assert [(row.source_path, row.publisher, row.entry_count) for row in inventory.files] == [
        ("DC/Characters/unsorted/hero.cbl", "DC", 1),
        ("Marvel/Events/event.cbl", "Marvel", 2),
        ("Other/unsorted/duplicate-a.cbl", "Other", 1),
        ("Other/unsorted/duplicate-b.cbl", "Other", 1),
        ("root.cbl", "(root)", 1),
    ]
    assert {(row.source_path, row.comicvine_pair_count) for row in inventory.files} == {
        ("DC/Characters/unsorted/hero.cbl", 0),
        ("Marvel/Events/event.cbl", 2),
        ("Other/unsorted/duplicate-a.cbl", 1),
        ("Other/unsorted/duplicate-b.cbl", 1),
        ("root.cbl", 1),
    }
    assert [
        (publisher.name, publisher.files, publisher.parsed, publisher.failed)
        for publisher in inventory.publishers
    ] == [
        ("(root)", 1, 1, 0),
        ("DC", 1, 1, 0),
        ("Marvel", 2, 1, 1),
        ("Other", 2, 2, 0),
    ]
    assert len(inventory.files[1].content_hash) == 64


def test_inventory_output_is_stable_across_repeats(tmp_path: Path) -> None:
    """Parsing and inventory serialization produce byte-identical repeatable output."""
    _write_initial_mirror(tmp_path)

    first_parsed, first_failures = parse_cbl_mirror(tmp_path)
    second_parsed, second_failures = parse_cbl_mirror(tmp_path)

    first = json.dumps(asdict(build_cbl_inventory(first_parsed, first_failures)), sort_keys=True)
    second = json.dumps(asdict(build_cbl_inventory(second_parsed, second_failures)), sort_keys=True)
    assert first == second


@pytest.mark.asyncio
async def test_inventory_only_cli_never_opens_a_database_session(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A full-fork inventory is an off-request, database-free operation."""
    _write_initial_mirror(tmp_path)
    (tmp_path / "Marvel" / "Broken" / "bad.cbl").write_text("<ReadingList><Books>")
    monkeypatch.setattr(
        sync_cbl_mirror,
        "AsyncSessionLocal",
        Mock(side_effect=AssertionError("inventory must not open a database session")),
    )
    sync = AsyncMock()
    monkeypatch.setattr(sync_cbl_mirror, "sync_cbl_lists", sync)

    result = await sync_cbl_mirror._run(_inventory_args(tmp_path, inventory_only=True))

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["mode"] == "inventory"
    assert payload["revision_sha"] == "abc123"
    assert payload["parsed_lists"] == 5
    assert payload["inventory"]["total_files"] == 6
    assert payload["inventory"]["failed_files"] == 1
    assert payload["inventory"]["total_entries"] == 6
    assert len(payload["parse_failures"]) == 1
    assert payload["parse_failures"][0]["source_path"] == "Marvel/Broken/bad.cbl"
    assert "malformed CBL XML" in payload["parse_failures"][0]["message"]
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_cli_dry_run_reports_stable_inventory_and_sync_counts(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Dry-run emits deterministic inventory plus reconciliation counters."""
    _write_initial_mirror(tmp_path)
    monkeypatch.setattr(sync_cbl_mirror, "AsyncSessionLocal", lambda: _FakeSession())
    sync = AsyncMock(return_value=_summary(dry_run=True, inserted_lists=6))
    monkeypatch.setattr(sync_cbl_mirror, "sync_cbl_lists", sync)

    first = await sync_cbl_mirror._run(_inventory_args(tmp_path, inventory_only=False, dry_run=True))
    first_payload = json.loads(capsys.readouterr().out)
    second = await sync_cbl_mirror._run(_inventory_args(tmp_path, inventory_only=False, dry_run=True))
    second_payload = json.loads(capsys.readouterr().out)

    assert first == second == 0
    assert first_payload == second_payload
    assert first_payload["mode"] == "dry_run"
    assert first_payload["inventory"]["total_files"] == 6
    assert first_payload["inventory"]["parsed_files"] == 6
    assert first_payload["dry_run"] is True
    assert first_payload["inserted_lists"] == 6
    assert sync.await_count == 2


def _summary(*, dry_run: bool, inserted_lists: int) -> CBLSyncSummary:
    """Build a deterministic CLI summary for fake-session tests."""
    return CBLSyncSummary(
        source_created=True,
        inserted_lists=inserted_lists,
        updated_lists=0,
        deactivated_lists=0,
        unchanged_lists=0,
        entries_written=6,
        identities_upserted=0,
        dry_run=dry_run,
        changed=True,
    )


@pytest.mark.asyncio
async def test_refresh_reconciles_legacy_repository_identity_in_place(
    async_db: AsyncSession,
    tmp_path: Path,
) -> None:
    """A legacy machine-path source identity becomes canonical without changing IDs."""
    _write_initial_mirror(tmp_path)
    parsed, failures = parse_cbl_mirror(tmp_path)
    legacy_repository = "/mnt/bigdata/CBL-ReadingLists"
    protected = frozenset(failure.source_path for failure in failures)

    await sync_cbl_lists(
        async_db,
        repository=legacy_repository,
        revision_sha="sha-1",
        parsed_lists=parsed,
        protected_paths=protected,
    )
    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    source_id = source.id
    list_ids = {
        item.source_path: item.id
        for item in (await async_db.execute(select(CBLSourceList))).scalars().all()
    }

    preview = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-2",
        parsed_lists=parsed,
        protected_paths=protected,
        repository_aliases=(legacy_repository,),
        dry_run=True,
    )
    assert preview.repository_reconciled is True
    assert preview.changed is True
    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    assert source.repository == legacy_repository

    applied = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-2",
        parsed_lists=parsed,
        protected_paths=protected,
        repository_aliases=(legacy_repository,),
    )
    assert applied.repository_reconciled is True
    assert applied.changed is True
    assert applied.inserted_lists == 0
    assert applied.updated_lists == 0
    assert applied.deactivated_lists == 0

    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    assert source.id == source_id
    assert source.repository == REPOSITORY
    assert {
        item.source_path: item.id
        for item in (await async_db.execute(select(CBLSourceList))).scalars().all()
    } == list_ids

    replay = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-2",
        parsed_lists=parsed,
        protected_paths=protected,
    )
    assert replay.repository_reconciled is False
    assert replay.changed is False


@pytest.mark.asyncio
async def test_refresh_is_idempotent_and_preserves_source_and_list_ids(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """Refresh keeps source/list identity, reconciles changes, and writes nothing on a replay."""
    _write_initial_mirror(tmp_path)
    parsed, failures = parse_cbl_mirror(tmp_path)
    first_synced_at = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    first = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-1",
        parsed_lists=parsed,
        protected_paths=frozenset(failure.source_path for failure in failures),
        synced_at=first_synced_at,
    )

    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    source_id = source.id
    lists_before = list((await async_db.execute(select(CBLSourceList))).scalars().all())
    list_ids = {item.source_path: item.id for item in lists_before}
    assert first.inserted_lists == 6
    assert first.changed is True

    _write(tmp_path / "DC" / "Characters" / "unsorted" / "hero.cbl", CHANGED_HERO_CBL)
    (tmp_path / "Other" / "unsorted" / "duplicate-a.cbl").unlink()
    (tmp_path / "Marvel" / "Broken" / "bad.cbl").write_text("<ReadingList><Books>")
    refresh_parsed, refresh_failures = parse_cbl_mirror(tmp_path)
    second_synced_at = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    second = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-2",
        parsed_lists=refresh_parsed,
        protected_paths=frozenset(failure.source_path for failure in refresh_failures),
        synced_at=second_synced_at,
    )

    assert second.inserted_lists == 0
    assert second.updated_lists == 1
    assert second.deactivated_lists == 1
    assert second.unchanged_lists == 3
    assert second.entries_written == 1
    assert second.changed is True

    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    assert source.id == source_id
    assert source.revision_sha == "sha-2"
    assert source.synced_at == second_synced_at

    refreshed_lists = list((await async_db.execute(select(CBLSourceList))).scalars().all())
    by_path = {item.source_path: item for item in refreshed_lists}
    assert {path: item.id for path, item in by_path.items()} == list_ids

    event_list = by_path["Marvel/Events/event.cbl"]
    assert event_list.active is True
    assert event_list.revision_sha == "sha-1"
    changed_hero = by_path["DC/Characters/unsorted/hero.cbl"]
    assert changed_hero.active is True
    assert changed_hero.revision_sha == "sha-2"
    removed = by_path["Other/unsorted/duplicate-a.cbl"]
    assert removed.active is False
    assert removed.revision_sha == "sha-2"
    unchanged_duplicate = by_path["Other/unsorted/duplicate-b.cbl"]
    assert unchanged_duplicate.active is True
    assert unchanged_duplicate.revision_sha == "sha-1"
    malformed = by_path["Marvel/Broken/bad.cbl"]
    assert malformed.active is True
    assert malformed.revision_sha == "sha-1"

    hero_entries = list(
        (
            await async_db.execute(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == changed_hero.id)
                .order_by(CBLSourceEntry.position)
            )
        )
        .scalars()
        .all()
    )
    assert [(entry.position, entry.issue_number) for entry in hero_entries] == [(1, "2")]
    malformed_entries = list(
        (
            await async_db.execute(
                select(CBLSourceEntry).where(CBLSourceEntry.list_id == malformed.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(malformed_entries) == 1
    removed_entries = list(
        (
            await async_db.execute(
                select(CBLSourceEntry).where(CBLSourceEntry.list_id == removed.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(removed_entries) == 1

    list_updated_at = {item.id: item.updated_at for item in refreshed_lists}
    writes: list[str] = []

    def _record_write(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record_write)
    try:
        replay = await sync_cbl_lists(
            async_db,
            repository=REPOSITORY,
            revision_sha="sha-2",
            parsed_lists=refresh_parsed,
            protected_paths=frozenset(failure.source_path for failure in refresh_failures),
            synced_at=datetime(2026, 10, 23, 12, 0, tzinfo=UTC),
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record_write)

    assert replay.changed is False
    assert replay.inserted_lists == 0
    assert replay.updated_lists == 0
    assert replay.deactivated_lists == 0
    assert replay.unchanged_lists == 4
    assert replay.entries_written == 0
    assert writes == []
    assert source.synced_at == second_synced_at
    assert {item.id: item.updated_at for item in refreshed_lists} == list_updated_at


@pytest.mark.asyncio
async def test_refresh_with_same_revision_and_hashes_writes_nothing(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """Replaying the recorded revision and file hashes emits no write statements."""
    _write_initial_mirror(tmp_path)
    parsed, failures = parse_cbl_mirror(tmp_path)
    protected = frozenset(failure.source_path for failure in failures)
    first_synced_at = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-1",
        parsed_lists=parsed,
        protected_paths=protected,
        synced_at=first_synced_at,
    )

    writes: list[str] = []

    def _record_write(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record_write)
    try:
        replay = await sync_cbl_lists(
            async_db,
            repository=REPOSITORY,
            revision_sha="sha-1",
            parsed_lists=parsed,
            protected_paths=protected,
            synced_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record_write)

    assert replay.changed is False
    assert replay.inserted_lists == 0
    assert replay.updated_lists == 0
    assert replay.deactivated_lists == 0
    assert replay.entries_written == 0
    assert replay.identities_upserted == 0
    assert writes == []
    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    assert source.synced_at == first_synced_at


@pytest.mark.asyncio
async def test_dry_run_reports_full_refresh_without_persisting_any_change(
    async_db: AsyncSession,
    tmp_path: Path,
) -> None:
    """A full changed/missing/malformed preview leaves every source and user-owned count untouched."""
    _write_initial_mirror(tmp_path)
    parsed, failures = parse_cbl_mirror(tmp_path)
    await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-1",
        parsed_lists=parsed,
        protected_paths=frozenset(failure.source_path for failure in failures),
        synced_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
    )
    identity_count = await async_db.scalar(select(func.count()).select_from(ExternalIdentity))

    _write(tmp_path / "DC" / "Characters" / "unsorted" / "hero.cbl", CHANGED_HERO_CBL)
    (tmp_path / "Other" / "unsorted" / "duplicate-a.cbl").unlink()
    (tmp_path / "Marvel" / "Broken" / "bad.cbl").write_text("<ReadingList><Books>")
    refresh_parsed, refresh_failures = parse_cbl_mirror(tmp_path)
    before_lists = list((await async_db.execute(select(CBLSourceList))).scalars().all())
    before_entries = await async_db.scalar(select(func.count()).select_from(CBLSourceEntry))

    summary = await sync_cbl_lists(
        async_db,
        repository=REPOSITORY,
        revision_sha="sha-2",
        parsed_lists=refresh_parsed,
        protected_paths=frozenset(failure.source_path for failure in refresh_failures),
        dry_run=True,
    )

    assert summary.dry_run is True
    assert summary.changed is True
    assert summary.inserted_lists == 0
    assert summary.updated_lists == 1
    assert summary.deactivated_lists == 1
    assert summary.unchanged_lists == 3
    assert summary.entries_written == 1

    source = await async_db.scalar(select(CBLSource))
    assert source is not None
    assert source.revision_sha == "sha-1"
    assert source.synced_at == datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    assert [
        (item.id, item.source_path, item.active, item.content_hash, item.revision_sha)
        for item in (await async_db.execute(select(CBLSourceList))).scalars().all()
    ] == [
        (item.id, item.source_path, item.active, item.content_hash, item.revision_sha)
        for item in before_lists
    ]
    assert await async_db.scalar(select(func.count()).select_from(CBLSourceEntry)) == before_entries
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == identity_count
