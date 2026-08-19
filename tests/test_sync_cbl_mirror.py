"""CLI tests for normalized CBL mirror synchronization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import TracebackType
from unittest.mock import AsyncMock

import pytest

from app.cbl_ingest import CBLParseFailure
from app.cbl_sync import CBLSyncSummary
from scripts import sync_cbl_mirror


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


class _FakeSessionFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


@pytest.mark.asyncio
async def test_cbl_sync_cli_skips_revision_already_synchronized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """An unchanged source revision exits before parsing or writing any CBL rows."""
    stored_revision = AsyncMock(return_value="abc123")
    parse = pytest.fail
    sync = AsyncMock()
    monkeypatch.setattr(sync_cbl_mirror, "_stored_revision", stored_revision)
    monkeypatch.setattr(sync_cbl_mirror, "parse_cbl_mirror", parse)
    monkeypatch.setattr(sync_cbl_mirror, "sync_cbl_lists", sync)

    result = await sync_cbl_mirror._run(
        argparse.Namespace(
            mirror_path=tmp_path,
            repository="JoshCLWren/CBL-ReadingLists",
            revision_sha="abc123",
            dry_run=False,
            force=False,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload == {
        "reason": "revision_already_synchronized",
        "repository": "JoshCLWren/CBL-ReadingLists",
        "revision_sha": "abc123",
        "skipped": True,
    }
    stored_revision.assert_awaited_once_with("JoshCLWren/CBL-ReadingLists")
    sync.assert_not_awaited()


@pytest.mark.asyncio
async def test_cbl_sync_cli_emits_machine_readable_partial_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Valid lists may sync while parse failures remain explicit in JSON and exit status."""
    failure = CBLParseFailure(
        source_path="broken/list.cbl",
        message="broken/list.cbl: malformed CBL XML",
    )
    monkeypatch.setattr(sync_cbl_mirror, "parse_cbl_mirror", lambda _path: ((), (failure,)))
    monkeypatch.setattr(sync_cbl_mirror, "AsyncSessionLocal", _FakeSessionFactory())
    stored_revision = AsyncMock(return_value=None)
    monkeypatch.setattr(sync_cbl_mirror, "_stored_revision", stored_revision)
    sync = AsyncMock(
        return_value=CBLSyncSummary(
            source_created=False,
            inserted_lists=0,
            updated_lists=0,
            deactivated_lists=1,
            unchanged_lists=4,
            entries_written=0,
            dry_run=True,
        )
    )
    monkeypatch.setattr(sync_cbl_mirror, "sync_cbl_lists", sync)

    result = await sync_cbl_mirror._run(
        argparse.Namespace(
            mirror_path=tmp_path,
            repository="JoshCLWren/CBL-ReadingLists",
            revision_sha="abc123",
            dry_run=True,
            force=False,
        )
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["dry_run"] is True
    assert payload["deactivated_lists"] == 1
    assert payload["repository"] == "JoshCLWren/CBL-ReadingLists"
    assert payload["revision_sha"] == "abc123"
    assert payload["skipped"] is False
    assert payload["parse_failures"] == [
        {
            "message": "broken/list.cbl: malformed CBL XML",
            "source_path": "broken/list.cbl",
        }
    ]
    stored_revision.assert_not_awaited()
    sync.assert_awaited_once()
    await_args = sync.await_args
    assert await_args is not None
    assert await_args.kwargs["dry_run"] is True
    assert await_args.kwargs["revision_sha"] == "abc123"
    assert await_args.kwargs["protected_paths"] == frozenset({"broken/list.cbl"})


@pytest.mark.asyncio
async def test_cbl_sync_cli_force_reconciles_matching_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Force mode bypasses the revision short-circuit for explicit recovery runs."""
    monkeypatch.setattr(sync_cbl_mirror, "parse_cbl_mirror", lambda _path: ((), ()))
    monkeypatch.setattr(sync_cbl_mirror, "AsyncSessionLocal", _FakeSessionFactory())
    stored_revision = AsyncMock(return_value="abc123")
    monkeypatch.setattr(sync_cbl_mirror, "_stored_revision", stored_revision)
    sync = AsyncMock(
        return_value=CBLSyncSummary(
            source_created=False,
            inserted_lists=0,
            updated_lists=0,
            deactivated_lists=0,
            unchanged_lists=1,
            entries_written=0,
            dry_run=False,
        )
    )
    monkeypatch.setattr(sync_cbl_mirror, "sync_cbl_lists", sync)

    result = await sync_cbl_mirror._run(
        argparse.Namespace(
            mirror_path=tmp_path,
            repository="JoshCLWren/CBL-ReadingLists",
            revision_sha="abc123",
            dry_run=False,
            force=True,
        )
    )

    assert result == 0
    stored_revision.assert_not_awaited()
    sync.assert_awaited_once()


def test_cbl_sync_cli_rejects_non_directory_mirror(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A missing mirror fails before opening a database session."""
    missing = tmp_path / "missing"
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_cbl_mirror.py",
            str(missing),
            "--revision-sha",
            "abc123",
        ],
    )

    result = sync_cbl_mirror.main()

    payload = json.loads(capsys.readouterr().err)
    assert result == 2
    assert payload == {
        "error": "mirror_path_not_directory",
        "mirror_path": str(missing),
    }
