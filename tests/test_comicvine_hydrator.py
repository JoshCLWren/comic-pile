"""Tests for read-only ComicVine hydration planning."""

from pathlib import Path

from comic_pile.comicvine_hydrator import HydrationTarget, build_report, inspect_local_snapshot
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
