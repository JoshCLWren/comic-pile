"""Edge coverage for ComicVine identity repair orchestration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from comic_pile.comicvine_identity_repair import ComicVineRepairContext
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError
from comic_pile.comicvine_repair_pipeline import (
    _candidate_from_rows,
    _exact_local_candidate,
    _integer,
    _object_result,
    _publisher_name,
    discover_live_candidates,
    repair_identity,
)
from comic_pile.local_comicvine import LocalComicVineSnapshot


def _snapshot(path: Path) -> LocalComicVineSnapshot:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE cv_volume (
            id INTEGER PRIMARY KEY,
            name TEXT,
            publisher TEXT,
            start_year INTEGER
        );
        CREATE TABLE cv_issue (
            id INTEGER PRIMARY KEY,
            volume_id INTEGER,
            issue_number TEXT,
            name TEXT
        );
        CREATE VIRTUAL TABLE cv_volume_fts USING fts5(
            name,
            content='cv_volume',
            content_rowid='id'
        );
        INSERT INTO cv_volume VALUES (10, 'X-Men', 'Marvel', 1991);
        INSERT INTO cv_issue VALUES (100, 10, '1', NULL);
        INSERT INTO cv_volume_fts(rowid, name) VALUES (10, 'X-Men');
        """
    )
    connection.commit()
    connection.close()
    return LocalComicVineSnapshot(path)


def test_pipeline_helpers_reject_invalid_provider_shapes() -> None:
    """Provider helper functions should normalize valid values and reject malformed ones."""
    assert _integer(7) == 7
    assert _integer("8") == 8
    assert _integer("8a") is None
    assert _integer(None) is None
    assert _publisher_name(" Marvel ") == "Marvel"
    assert _publisher_name({"name": " DC Comics "}) == "DC Comics"
    assert _publisher_name({"name": ""}) is None
    assert _publisher_name(3) is None
    with pytest.raises(ComicVineError, match="object result"):
        _object_result({"results": []}, "issue")


def test_candidate_from_rows_requires_ids_title_and_issue_match() -> None:
    """Search discovery alone should never produce an unvalidated issue candidate."""
    context = ComicVineRepairContext(title="X-Men", issue_label="1")
    assert _candidate_from_rows({}, {}, context, source="test") is None
    assert (
        _candidate_from_rows(
            {"id": 10, "name": "X-Men"},
            {"id": 100, "issue_number": "2"},
            context,
            source="test",
        )
        is None
    )
    candidate = _candidate_from_rows(
        {
            "id": "10",
            "name": "X-Men",
            "publisher": {"name": "Marvel"},
            "start_year": "1991",
        },
        {"id": "100", "issue_number": "9", "name": "1"},
        context,
        source="test",
    )
    assert candidate is not None
    assert candidate.issue_id == 100
    assert candidate.volume_id == 10
    assert candidate.publisher == "Marvel"
    assert candidate.start_year == 1991


def test_exact_local_candidate_handles_missing_and_invalid_rows(tmp_path: Path) -> None:
    """Exact local lookup should fail safely when issue or volume evidence is incomplete."""
    snapshot = _snapshot(tmp_path / "localcv.db")
    context = ComicVineRepairContext(title="X-Men", issue_label="1")
    assert _exact_local_candidate(snapshot, 999, context) is None
    exact = _exact_local_candidate(snapshot, 100, context)
    assert exact is not None
    assert exact.issue_id == 100


@pytest.mark.asyncio
async def test_live_discovery_skips_bad_search_rows_and_deduplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live discovery should validate rows and keep one stable copy of each provider issue."""
    client = ComicVineClient("secret", tmp_path / "cache")

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        if endpoint == "search":
            return {
                "status_code": 1,
                "results": [
                    "bad-row",
                    {"id": "bad", "name": "X-Men"},
                    {"id": 10, "name": "X-Men", "publisher": "Marvel"},
                    {"id": 11, "name": "X-Men", "publisher": "Marvel"},
                ],
            }
        if endpoint == "issues":
            return {
                "status_code": 1,
                "number_of_total_results": 2,
                "results": [
                    {"id": 100, "issue_number": "1", "volume": {"id": 10}},
                    {"id": 100, "issue_number": "1", "volume": {"id": 10}},
                ],
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(client, "_request_sync", fake_request)
    candidates = await discover_live_candidates(
        client,
        ComicVineRepairContext(title="X-Men", issue_label="1"),
    )
    assert [(candidate.volume_id, candidate.issue_id) for candidate in candidates] == [(10, 100)]


@pytest.mark.asyncio
async def test_live_discovery_rejects_non_list_search_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed search envelopes should fail loudly instead of becoming empty evidence."""
    client = ComicVineClient("secret", tmp_path / "cache")

    def fake_request(endpoint: str, params: object) -> dict[str, object]:
        return {"status_code": 1, "results": {}}

    monkeypatch.setattr(client, "_request_sync", fake_request)
    with pytest.raises(ComicVineError, match="results list"):
        await discover_live_candidates(
            client,
            ComicVineRepairContext(title="X-Men", issue_label="1"),
        )


@pytest.mark.asyncio
async def test_embedded_id_without_local_or_live_evidence_falls_through(
    tmp_path: Path,
) -> None:
    """An unvalidated embedded ID must not be confirmed merely because the CBL supplied it."""
    decision, scores = await repair_identity(
        snapshot=LocalComicVineSnapshot(tmp_path / "missing.db"),
        client=None,
        context=ComicVineRepairContext(title="X-Men", issue_label="1"),
        thread_issue_labels=["1"],
        embedded_cbl_issue_id=999,
    )
    assert decision.status == "unresolved"
    assert scores == ()
