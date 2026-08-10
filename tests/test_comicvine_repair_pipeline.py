"""Tests for local-first ComicVine identity repair orchestration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from comic_pile.comicvine_identity_repair import ComicVineRepairContext
from comic_pile.comicvine_provider import ComicVineClient
from comic_pile.comicvine_repair_pipeline import repair_identity
from comic_pile.local_comicvine import LocalComicVineSnapshot


def _local_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cv_volume (id INTEGER PRIMARY KEY, name TEXT, publisher TEXT, start_year INTEGER);
        CREATE TABLE cv_issue (id INTEGER PRIMARY KEY, volume_id INTEGER, issue_number TEXT, name TEXT);
        CREATE VIRTUAL TABLE cv_volume_fts USING fts5(name, content='cv_volume', content_rowid='id');
        INSERT INTO cv_volume VALUES (77, 'Planetary', 'WildStorm', 1999);
        INSERT INTO cv_issue VALUES (700, 77, '15', NULL);
        INSERT INTO cv_volume_fts(rowid, name) VALUES (77, 'Planetary');
        """
    )
    connection.commit()
    connection.close()


@pytest.mark.asyncio
async def test_repair_prefers_local_candidates_without_live_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A validated local candidate should avoid spending any live ComicVine request budget."""
    database = tmp_path / "localcv.db"
    _local_fixture(database)
    client = ComicVineClient("secret", tmp_path / "cache")

    def fail_live_request(endpoint: str, params: object) -> dict[str, object]:
        raise AssertionError(f"unexpected live request: {endpoint} {params}")

    monkeypatch.setattr(client, "_request_sync", fail_live_request)

    decision, scores = await repair_identity(
        snapshot=LocalComicVineSnapshot(database),
        client=client,
        context=ComicVineRepairContext(title="Planetary", issue_label="15"),
        thread_issue_labels=["14", "15", "16"],
    )

    assert len(scores) == 1
    assert scores[0].candidate.issue_id == 700
    assert scores[0].candidate.source == "comicvine-local-sqlite"
    assert decision.status in {"candidate", "confirmed"}


@pytest.mark.asyncio
async def test_repair_uses_live_search_only_after_local_miss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent local snapshot should fall through to validated live volume/issue evidence."""
    client = ComicVineClient("secret", tmp_path / "cache")
    observed: list[str] = []

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        observed.append(endpoint)
        if endpoint == "search":
            return {
                "status_code": 1,
                "results": [
                    {
                        "id": 88,
                        "name": "B.P.R.D.: War on Frogs",
                        "publisher": {"name": "Dark Horse Comics"},
                        "start_year": 2006,
                    }
                ],
            }
        if endpoint == "issues":
            return {
                "status_code": 1,
                "number_of_total_results": 1,
                "results": [
                    {
                        "id": 801,
                        "issue_number": "5",
                        "name": "Revival",
                        "volume": {"id": 88},
                    }
                ],
            }
        raise AssertionError(f"unexpected endpoint: {endpoint}")

    monkeypatch.setattr(client, "_request_sync", fake_request)

    decision, scores = await repair_identity(
        snapshot=LocalComicVineSnapshot(tmp_path / "missing.db"),
        client=client,
        context=ComicVineRepairContext(
            title="B.P.R.D.: War on Frogs",
            issue_label="Revival",
            publisher="Dark Horse Comics",
        ),
        thread_issue_labels=["1", "2", "3", "4", "Revival"],
    )

    assert observed == ["search", "issues"]
    assert len(scores) == 1
    assert scores[0].candidate.issue_id == 801
    assert scores[0].candidate.source == "comicvine-live"
    assert "issue name matches human label" in scores[0].evidence
    assert decision.status in {"candidate", "confirmed"}
