"""Tests for local ComicVine identity candidate discovery."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from comic_pile.comicvine_candidate_discovery import discover_local_candidates, snapshot_sync_time
from comic_pile.comicvine_identity_repair import ComicVineRepairContext
from comic_pile.local_comicvine import LocalComicVineSnapshot


def _build_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cv_volume (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            publisher TEXT,
            start_year INTEGER
        );
        CREATE TABLE cv_issue (
            id INTEGER PRIMARY KEY,
            volume_id INTEGER NOT NULL,
            issue_number TEXT NOT NULL,
            name TEXT
        );
        CREATE VIRTUAL TABLE cv_volume_fts USING fts5(name, content='cv_volume', content_rowid='id');
        CREATE TABLE cv_sync_metadata (key TEXT, value TEXT);

        INSERT INTO cv_volume VALUES (10, 'Justice League America', 'DC Comics', 1987);
        INSERT INTO cv_volume VALUES (20, 'Justice League America', 'Foreign Reprints', 2002);
        INSERT INTO cv_issue VALUES (101, 10, '1', NULL);
        INSERT INTO cv_issue VALUES (102, 10, '2', NULL);
        INSERT INTO cv_issue VALUES (103, 10, '3', NULL);
        INSERT INTO cv_issue VALUES (201, 20, '2', NULL);
        INSERT INTO cv_volume_fts(rowid, name) VALUES (10, 'Justice League America');
        INSERT INTO cv_volume_fts(rowid, name) VALUES (20, 'Justice League America');
        INSERT INTO cv_sync_metadata VALUES ('last_sync', '2026-01-09T00:00:00Z');
        """
    )
    connection.commit()
    connection.close()


def test_discovery_validates_issue_rows_and_derives_local_segment(tmp_path: Path) -> None:
    """FTS hits should become issue-level candidates only after exact local issue validation."""
    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)

    candidates = discover_local_candidates(
        snapshot,
        ComicVineRepairContext(
            title="Justice League America",
            issue_label="2",
            previous_issue_label="1",
            next_issue_label="3",
        ),
        thread_issue_labels=["1", "2", "3", "Annual 1"],
    )

    assert [(candidate.volume_id, candidate.issue_id) for candidate in candidates] == [
        (10, 102),
        (20, 201),
    ]
    original, reprint = candidates
    assert original.previous_issue_exists is True
    assert original.next_issue_exists is True
    assert (original.segment_start, original.segment_end) == ("1", "3")
    assert reprint.previous_issue_exists is False
    assert reprint.next_issue_exists is False
    assert (reprint.segment_start, reprint.segment_end) == ("2", "2")


def test_snapshot_sync_time_exposes_hard_freshness_boundary(tmp_path: Path) -> None:
    """Candidate scoring can use the snapshot's actual sync timestamp as a freshness bound."""
    database = tmp_path / "localcv.db"
    _build_fixture(database)

    synced_at = snapshot_sync_time(LocalComicVineSnapshot(database))

    assert synced_at is not None
    assert synced_at.isoformat() == "2026-01-09T00:00:00+00:00"
