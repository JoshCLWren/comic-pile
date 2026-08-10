"""Tests for read-only ComicVine hydration planning."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from comic_pile.comicvine_hydrator import (
    HydrationTarget,
    build_report,
    enumerate_user_issues,
    inspect_local_snapshot,
    write_report,
)
from comic_pile.local_comicvine import LocalComicVineResult


class FakeSnapshot:
    """Minimal local snapshot fake for deterministic hydrator tests."""

    def __init__(self, rows: dict[int, LocalComicVineResult] | None = None) -> None:
        """Initialize fake rows."""
        self.rows = rows or {}
        self.path = Path("/tmp/comicvine.db")
        self.available = True

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one fake issue row."""
        return self.rows.get(issue_id)

    def sync_metadata(self) -> dict[str, object]:
        """Return deterministic freshness metadata."""
        return {"0": {"synced_at": "2026-01-09T00:00:00Z"}}


def target(*, external_id: int | None, issue_number: str = "12") -> HydrationTarget:
    """Build one compact hydration target fixture."""
    return HydrationTarget(
        issue_id=10,
        thread_id=4,
        thread_title="X-Men",
        issue_number=issue_number,
        position=12,
        comicvine_issue_id=external_id,
    )


def test_unmapped_issue_remains_unresolved() -> None:
    """Never guess provider identity when no confirmed mapping exists."""
    result = inspect_local_snapshot(target(external_id=None), FakeSnapshot())

    assert result.status == "unresolved"
    assert result.comicvine_issue_id is None


def test_confirmed_identity_local_miss_is_not_reinterpreted() -> None:
    """A stale/local miss stays attached to its confirmed provider identity."""
    result = inspect_local_snapshot(target(external_id=123), FakeSnapshot())

    assert result.status == "local-miss"
    assert result.comicvine_issue_id == 123


def test_human_label_preserves_confirmed_mapping() -> None:
    """Human issue labels need not equal ComicVine numeric issue text."""
    snapshot = FakeSnapshot(
        {
            55: LocalComicVineResult(
                data={"issue_number": "5", "volume_id": 99, "name": "Revival"}
            )
        }
    )

    result = inspect_local_snapshot(target(external_id=55, issue_number="Revival"), snapshot)

    assert result.status == "matched"
    assert "differs" in result.detail


def test_report_counts_are_deterministic() -> None:
    """Summary categories match per-issue report states."""
    snapshot = FakeSnapshot(
        {1: LocalComicVineResult(data={"issue_number": "1", "volume_id": 10})}
    )
    targets = [
        target(external_id=1, issue_number="1"),
        HydrationTarget(11, 4, "X-Men", "2", 13, 2),
        HydrationTarget(12, 4, "X-Men", "3", 14, None),
    ]

    report = build_report(targets, snapshot)

    assert report["summary"] == {
        "total": 3,
        "matched": 1,
        "local-miss": 1,
        "unresolved": 1,
    }


async def test_enumerate_user_issues_reuses_confirmed_identity() -> None:
    """Confirmed provider IDs are attached while enumerating user-owned issues."""
    issue = SimpleNamespace(id=10, issue_number="Revival", position=7)
    thread = SimpleNamespace(id=4, title="B.P.R.D.: War on Frogs")
    issue_rows = Mock()
    issue_rows.all.return_value = [(issue, thread)]
    mapping_rows = Mock()
    mapping_rows.all.return_value = [(10, "55")]
    db = AsyncMock()
    db.execute.side_effect = [issue_rows, mapping_rows]

    targets = await enumerate_user_issues(db, user_id=1)

    assert targets == [
        HydrationTarget(
            issue_id=10,
            thread_id=4,
            thread_title="B.P.R.D.: War on Frogs",
            issue_number="Revival",
            position=7,
            comicvine_issue_id=55,
        )
    ]
    assert db.execute.await_count == 2


async def test_enumerate_user_issues_ignores_invalid_confirmed_identity() -> None:
    """Malformed external IDs do not become guessed ComicVine mappings."""
    issue = SimpleNamespace(id=10, issue_number="12", position=12)
    thread = SimpleNamespace(id=4, title="X-Men")
    issue_rows = Mock()
    issue_rows.all.return_value = [(issue, thread)]
    mapping_rows = Mock()
    mapping_rows.all.return_value = [(10, "not-an-integer")]
    db = AsyncMock()
    db.execute.side_effect = [issue_rows, mapping_rows]

    targets = await enumerate_user_issues(db, user_id=1, include_test_threads=True)

    assert targets[0].comicvine_issue_id is None
    assert db.execute.await_count == 2


def test_write_report_creates_parent_and_replaces_temporary_file(tmp_path: Path) -> None:
    """Report writes create parent directories and leave no temporary artifact behind."""
    destination = tmp_path / "nested" / "hydration.json"
    report: dict[str, object] = {"summary": {"total": 1}, "issues": [{"issue_id": 10}]}

    write_report(report, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert not destination.with_suffix(".json.tmp").exists()
