"""Regression coverage for local-first ComicVine continuity resolution."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/backfill_read_comicvine.py"


def _module() -> ModuleType:
    """Import the operator CLI without treating scripts/ as a package."""
    module_name = "backfill_read_comicvine_local_continuity"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


@pytest.mark.asyncio
async def test_local_title_roster_can_cross_a_confirmed_series_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale/partial anchor must not veto a uniquely proven local predecessor volume."""
    cli = _module()
    resolver = cli._load_script_module(
        "_test_local_continuity_resolver",
        cli.RESOLUTION_HELPER,
    )
    work = resolver.ThreadWork(
        thread_id=305,
        title="Uncanny X-Men",
        issues=[
            resolver.IssueWork(issue_id=36, issue_number="36", position=36),
            resolver.IssueWork(issue_id=37, issue_number="37", position=37),
        ],
        confirmed_series=[
            resolver.SeriesEvidence(
                volume_id=3092,
                name="The Uncanny X-Men",
                start_year=1981,
                source="confirmed-series",
            )
        ],
        sibling_volumes=[
            resolver.SeriesEvidence(
                volume_id=115285,
                name="Uncanny X-Men",
                start_year=None,
                source="sibling-volume",
            ),
            resolver.SeriesEvidence(
                volume_id=159189,
                name="Uncanny X-Men",
                start_year=None,
                source="sibling-volume",
            ),
        ],
    )

    class LocalOnlyClient:
        """Expose local APIs only so any provider dependency explodes immediately."""

        _local_db = object()

        def search_local_volumes(self, query_title: str) -> list[dict[str, object]]:
            assert query_title == "Uncanny X-Men"
            return [
                {
                    "id": 2133,
                    "name": "The X-Men",
                    "aliases": "The All-New All-Different X-Men\nThe Uncanny X-Men",
                    "start_year": 1963,
                    "count_of_issues": 141,
                    "description": "Continues through issue #141.",
                },
                {
                    "id": 3092,
                    "name": "The Uncanny X-Men",
                    "aliases": None,
                    "start_year": 1981,
                    "count_of_issues": 405,
                    "description": "Continuation beginning with issue #142.",
                },
                {
                    "id": 115285,
                    "name": "Uncanny X-Men",
                    "aliases": None,
                    "start_year": 2018,
                    "count_of_issues": 22,
                    "description": None,
                },
                {
                    "id": 159189,
                    "name": "Uncanny X-Men",
                    "aliases": None,
                    "start_year": 2024,
                    "count_of_issues": 21,
                    "description": None,
                },
            ]

        def _fetch_local_volume_issues(
            self,
            volume_id: int,
        ) -> list[dict[str, object]] | None:
            rows = {
                2133: [
                    {"id": 2036, "issue_number": "36", "volume": {"id": 2133}},
                    {"id": 2037, "issue_number": "37", "volume": {"id": 2133}},
                ],
                3092: [
                    {"id": 3142, "issue_number": "142", "volume": {"id": 3092}},
                    {"id": 3143, "issue_number": "143", "volume": {"id": 3092}},
                ],
                115285: [
                    {"id": 115001, "issue_number": "1", "volume": {"id": 115285}},
                    {"id": 115002, "issue_number": "2", "volume": {"id": 115285}},
                ],
                159189: [
                    {"id": 159001, "issue_number": "1", "volume": {"id": 159189}},
                    {"id": 159002, "issue_number": "2", "volume": {"id": 159189}},
                ],
            }
            return rows.get(volume_id)

    persist_issue = AsyncMock(return_value=True)
    persist_series = AsyncMock()
    monkeypatch.setattr(resolver, "_persist_issue_mapping", persist_issue)
    monkeypatch.setattr(resolver, "_persist_thread_series", persist_series)

    result = await cli._resolve_thread_from_local_evidence(
        resolver,
        object(),
        LocalOnlyClient(),
        user_id=1,
        work=work,
        roster_cache={},
    )

    assert result is not None
    assert result.status == "resolved"
    assert result.mapped == 2
    assert result.remaining == 0
    assert result.volume_ids == [2133]
    persist_series.assert_not_awaited()
    assert persist_issue.await_count == 2
    assert {
        call.kwargs["volume_id"] for call in persist_issue.await_args_list
    } == {2133}
