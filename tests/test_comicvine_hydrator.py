"""Tests for read-only ComicVine hydration planning."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from comic_pile.comicvine_hydrator import (
    HydrationTarget,
    VolumeSegment,
    apply_local_volume_segments,
    build_report,
    enumerate_user_issues,
    inspect_local_snapshot,
    load_volume_segments,
    write_report,
)
from comic_pile.local_comicvine import LocalComicVineResult


class FakeSnapshot:
    """Minimal local snapshot fake for deterministic hydrator tests."""

    def __init__(
        self,
        rows: dict[int, LocalComicVineResult] | None = None,
        volume_rows: dict[int, list[LocalComicVineResult]] | None = None,
    ) -> None:
        """Initialize fake rows."""
        self.rows = rows or {}
        self.volume_rows = volume_rows or {}
        self.path = Path("/tmp/comicvine.db")
        self.available = True

    def get_issue(self, issue_id: int) -> LocalComicVineResult | None:
        """Return one fake issue row."""
        return self.rows.get(issue_id)

    def get_volume_issues(self, volume_id: int) -> list[LocalComicVineResult]:
        """Return fake issues for one provider volume."""
        return self.volume_rows.get(volume_id, [])

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


async def test_unmapped_issue_remains_unresolved() -> None:
    """Never guess provider identity when no confirmed mapping exists."""
    result = await inspect_local_snapshot(target(external_id=None), FakeSnapshot())

    assert result.status == "unresolved"
    assert result.comicvine_issue_id is None


async def test_confirmed_identity_local_miss_is_not_reinterpreted() -> None:
    """A stale/local miss stays attached to its confirmed provider identity."""
    result = await inspect_local_snapshot(target(external_id=123), FakeSnapshot())

    assert result.status == "local-miss"
    assert result.comicvine_issue_id == 123


async def test_incomplete_local_row_remains_a_local_miss() -> None:
    """Incomplete snapshot rows never masquerade as hydrated matches."""
    snapshot = FakeSnapshot(
        {
            55: LocalComicVineResult(
                data={"issue_number": "5"},
                complete=False,
            )
        }
    )

    result = await inspect_local_snapshot(target(external_id=55), snapshot)

    assert result.status == "local-miss"
    assert result.comicvine_issue_id == 55
    assert "required hydration data is missing" in result.detail


async def test_human_label_preserves_confirmed_mapping() -> None:
    """Human issue labels need not equal ComicVine numeric issue text."""
    snapshot = FakeSnapshot(
        {
            55: LocalComicVineResult(
                data={"issue_number": "5", "volume_id": 99, "name": "Revival"}
            )
        }
    )

    result = await inspect_local_snapshot(
        target(external_id=55, issue_number="Revival"),
        snapshot,
    )

    assert result.status == "matched"
    assert "differs" in result.detail


async def test_report_counts_are_deterministic() -> None:
    """Summary categories match per-issue report states."""
    snapshot = FakeSnapshot(
        {1: LocalComicVineResult(data={"issue_number": "1", "volume_id": 10})}
    )
    targets = [
        target(external_id=1, issue_number="1"),
        HydrationTarget(11, 4, "X-Men", "2", 13, 2),
        HydrationTarget(12, 4, "X-Men", "3", 14, None),
    ]

    report = await build_report(targets, snapshot)

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


async def test_conflicting_confirmed_identities_are_order_independent() -> None:
    """Conflicting confirmed IDs stay unresolved regardless of database row order."""
    issue = SimpleNamespace(id=10, issue_number="12", position=12)
    thread = SimpleNamespace(id=4, title="X-Men")

    async def enumerate_with_rows(rows: list[tuple[int, str]]) -> HydrationTarget:
        issue_rows = Mock()
        issue_rows.all.return_value = [(issue, thread)]
        mapping_rows = Mock()
        mapping_rows.all.return_value = rows
        db = AsyncMock()
        db.execute.side_effect = [issue_rows, mapping_rows]
        return (await enumerate_user_issues(db, user_id=1))[0]

    first = await enumerate_with_rows([(10, "55"), (10, "56")])
    reversed_order = await enumerate_with_rows([(10, "56"), (10, "55")])

    assert first.comicvine_issue_id is None
    assert reversed_order.comicvine_issue_id is None


async def test_volume_segments_split_one_thread_across_provider_volumes() -> None:
    """Justice League/JLI/JLA-style title transitions resolve issue-by-issue."""
    targets = [
        HydrationTarget(101, 77, "Justice League America", "1", 1),
        HydrationTarget(107, 77, "Justice League America", "7", 7),
        HydrationTarget(126, 77, "Justice League America", "26", 26),
    ]
    snapshot = FakeSnapshot(
        volume_rows={
            10: [LocalComicVineResult(data={"id": 1001, "issue_number": "1"})],
            20: [LocalComicVineResult(data={"id": 2007, "issue_number": "7"})],
            30: [LocalComicVineResult(data={"id": 3026, "issue_number": "26"})],
        }
    )
    segments = [
        VolumeSegment(77, 1, 6, 10),
        VolumeSegment(77, 7, 25, 20),
        VolumeSegment(77, 26, 61, 30),
    ]

    resolved = await apply_local_volume_segments(targets, snapshot, segments)

    assert [item.comicvine_issue_id for item in resolved] == [1001, 2007, 3026]


async def test_volume_segment_can_match_human_label_by_provider_issue_name() -> None:
    """Composite segments support labels such as Revival without forcing numeric equality."""
    snapshot = FakeSnapshot(
        volume_rows={
            99: [
                LocalComicVineResult(data={"id": 550, "issue_number": "5", "name": "Revival"})
            ]
        }
    )
    targets = [HydrationTarget(10, 4, "B.P.R.D.: War on Frogs", "Revival", 5)]

    resolved = await apply_local_volume_segments(
        targets,
        snapshot,
        [VolumeSegment(4, 1, 5, 99)],
    )

    assert resolved[0].comicvine_issue_id == 550


async def test_volume_segment_never_replaces_confirmed_issue_identity() -> None:
    """Segment evidence is subordinate to an existing confirmed issue mapping."""
    snapshot = FakeSnapshot(
        volume_rows={10: [LocalComicVineResult(data={"id": 999, "issue_number": "1"})]}
    )
    targets = [HydrationTarget(101, 77, "Justice League America", "1", 1, 123)]

    resolved = await apply_local_volume_segments(
        targets,
        snapshot,
        [VolumeSegment(77, 1, 6, 10)],
    )

    assert resolved[0].comicvine_issue_id == 123


async def test_ambiguous_segment_label_remains_unresolved() -> None:
    """Duplicate provider labels never become an arbitrary issue mapping."""
    snapshot = FakeSnapshot(
        volume_rows={
            10: [
                LocalComicVineResult(data={"id": 1, "issue_number": "1"}),
                LocalComicVineResult(data={"id": 2, "issue_number": "1"}),
            ]
        }
    )
    targets = [HydrationTarget(101, 77, "Composite", "1", 1)]

    resolved = await apply_local_volume_segments(
        targets,
        snapshot,
        [VolumeSegment(77, 1, 6, 10)],
    )

    assert resolved[0].comicvine_issue_id is None


def test_load_volume_segments_rejects_overlaps(tmp_path: Path) -> None:
    """Overlapping segment evidence is rejected before any hydration work begins."""
    path = tmp_path / "segments.json"
    path.write_text(
        json.dumps(
            {
                "segments": [
                    {
                        "thread_id": 77,
                        "start_position": 1,
                        "end_position": 10,
                        "comicvine_volume_id": 10,
                    },
                    {
                        "thread_id": 77,
                        "start_position": 10,
                        "end_position": 20,
                        "comicvine_volume_id": 20,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="overlapping volume segments"):
        load_volume_segments(path)


def test_write_report_creates_parent_and_replaces_temporary_file(tmp_path: Path) -> None:
    """Report writes create parent directories and leave no temporary artifact behind."""
    destination = tmp_path / "nested" / "hydration.json"
    report: dict[str, object] = {"summary": {"total": 1}, "issues": [{"issue_id": 10}]}

    write_report(report, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    assert destination.read_text(encoding="utf-8").endswith("\n")
    assert list(destination.parent.glob(".hydration.json.*.tmp")) == []
