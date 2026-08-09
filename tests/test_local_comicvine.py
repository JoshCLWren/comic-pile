"""Tests for the developer-local ComicVine SQLite adapter."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from comic_pile.local_comicvine import LocalComicVineSnapshot


def _build_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cv_volume (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            aliases TEXT,
            start_year INTEGER
        );
        CREATE TABLE cv_issue (
            id INTEGER PRIMARY KEY,
            volume_id INTEGER NOT NULL,
            issue_number TEXT NOT NULL,
            character_credits TEXT,
            person_credits TEXT,
            team_credits TEXT,
            story_arc_credits TEXT
        );
        CREATE VIRTUAL TABLE cv_volume_fts USING fts5(name, aliases, content='cv_volume', content_rowid='id');
        CREATE TABLE cv_sync_metadata (key TEXT, value TEXT);
        INSERT INTO cv_volume VALUES (122077, 'House of X', 'HOX', 2019);
        INSERT INTO cv_issue VALUES (
            819479,
            122077,
            '1',
            '[{"id": 1, "name": "Cyclops"}]',
            '[{"id": 2, "name": "Jonathan Hickman", "role": "writer"}]',
            '[{"id": 3, "name": "X-Men"}]',
            '[{"id": 4, "name": "Dawn of X"}]'
        );
        INSERT INTO cv_volume_fts(rowid, name, aliases) VALUES (122077, 'House of X', 'HOX');
        INSERT INTO cv_sync_metadata VALUES ('last_sync', '2026-01-09T00:00:00Z');
        """
    )
    connection.commit()
    connection.close()


def test_exact_local_volume_and_issue_lookup_avoids_fallback(tmp_path: Path) -> None:
    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)
    calls: list[int] = []

    volume = snapshot.get_volume(122077)
    issue = snapshot.get_issue_or_fallback(
        819479,
        lambda issue_id: calls.append(issue_id) or {"id": issue_id},
    )

    assert volume is not None
    assert volume.data["name"] == "House of X"
    assert issue.provenance == "comicvine-local-sqlite"
    assert issue.data["story_arc_credits"] == [{"id": 4, "name": "Dawn of X"}]
    assert issue.data["person_credits"] == [
        {"id": 2, "name": "Jonathan Hickman", "role": "writer"}
    ]
    assert calls == []


def test_missing_or_incomplete_issue_falls_back(tmp_path: Path) -> None:
    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)

    result = snapshot.get_issue_or_fallback(999999, lambda issue_id: {"id": issue_id, "name": "live"})

    assert result.provenance == "comicvine-live"
    assert result.data == {"id": 999999, "name": "live"}


def test_snapshot_is_optional_and_read_only(tmp_path: Path) -> None:
    missing = LocalComicVineSnapshot(tmp_path / "missing.db")

    assert missing.available is False
    assert missing.get_issue(819479) is None
    assert missing.search_volumes("House") == []

    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)
    with snapshot._connect() as connection:
        try:
            connection.execute("DELETE FROM cv_issue")
        except sqlite3.OperationalError as error:
            assert "readonly" in str(error).lower()
        else:
            raise AssertionError("snapshot connection unexpectedly allowed a write")


def test_fts_candidates_are_ranked_but_not_confirmed(tmp_path: Path) -> None:
    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)

    candidates = snapshot.search_volumes("House")

    assert len(candidates) == 1
    assert candidates[0].data["name"] == "House of X"
    assert candidates[0].complete is False


def test_sync_metadata_exposes_snapshot_freshness(tmp_path: Path) -> None:
    database = tmp_path / "localcv.db"
    _build_fixture(database)
    snapshot = LocalComicVineSnapshot(database)

    metadata = snapshot.sync_metadata()

    assert metadata["0"] == {"key": "last_sync", "value": "2026-01-09T00:00:00Z"}
