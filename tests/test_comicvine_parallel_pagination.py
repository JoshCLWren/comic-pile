"""Tests for parallel pagination in ComicVine provider."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from comic_pile.comicvine_provider import (
    ComicVineClient,
    ComicVineError,
    ComicVineResponse,
)
from app.services.comicvine_resolution import get_comicvine_series_issues


def _make_client(tmp_path: Path) -> ComicVineClient:
    """Build a real provider client backed by a temporary cache directory."""
    return ComicVineClient("secret", tmp_path)


def _probe_response(total_results: int) -> ComicVineResponse:
    """Build the count-probe response consumed by parallel pagination."""
    return ComicVineResponse(
        payload={"number_of_total_results": total_results, "results": []},
        from_cache=False,
        cache_key="count_probe",
    )


def _issue_rows(start: int, stop: int, *, volume_id: int = 100) -> list[dict[str, object]]:
    """Build ordered provider rows with ids from start to stop (inclusive)."""
    return [
        {
            "id": issue_id,
            "issue_number": str(issue_id),
            "name": f"Issue {issue_id}",
            "volume": {"id": volume_id},
        }
        for issue_id in range(start, stop + 1)
    ]


class TestComicVineParallelPagination:
    """Test parallel pagination functionality in ComicVine provider."""

    @pytest.mark.asyncio
    async def test_parallel_pagination_complete_results(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that parallel pagination returns all expected issues in correct order."""
        client = _make_client(tmp_path)
        page1_rows = _issue_rows(1, 100)
        page2_rows = _issue_rows(101, 200)
        page3_rows = _issue_rows(201, 250)

        probe_request = AsyncMock(return_value=_probe_response(250))
        monkeypatch.setattr(client, "request", probe_request)
        monkeypatch.setattr(
            client,
            "_fetch_single_page_issues",
            AsyncMock(side_effect=[page1_rows, page2_rows, page3_rows]),
        )

        result = await client._fetch_volume_issues_parallel(100)

        assert len(result) == 250
        issue_ids = [issue["id"] for issue in result]
        assert issue_ids == list(range(1, 251))
        for issue in result:
            volume = issue.get("volume")
            assert isinstance(volume, dict)
            assert volume.get("id") == 100
        probe_request.assert_called_once_with(
            "issues",
            "issues",
            {"filter": "volume:100", "limit": 1, "offset": 0},
            refresh=False,
        )

    @pytest.mark.asyncio
    async def test_parallel_pagination_single_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that single page volumes use the optimized single page path."""
        client = _make_client(tmp_path)
        page_rows = _issue_rows(1, 50)

        monkeypatch.setattr(client, "request", AsyncMock(return_value=_probe_response(50)))
        fetch_page = AsyncMock(return_value=page_rows)
        monkeypatch.setattr(client, "_fetch_single_page_issues", fetch_page)

        result = await client._fetch_volume_issues_parallel(100)

        assert len(result) == 50
        for issue in result:
            volume = issue.get("volume")
            assert isinstance(volume, dict)
            assert volume.get("id") == 100
        fetch_page.assert_called_once_with(100, 0, False)

    @pytest.mark.asyncio
    async def test_parallel_pagination_error_handling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test error handling when some pages fail."""
        client = _make_client(tmp_path)

        monkeypatch.setattr(client, "request", AsyncMock(return_value=_probe_response(250)))
        monkeypatch.setattr(
            client,
            "_fetch_single_page_issues",
            AsyncMock(
                side_effect=[
                    _issue_rows(1, 100),
                    ComicVineError("API request failed"),
                ]
            ),
        )

        with pytest.raises(ComicVineError, match="API request failed"):
            await client._fetch_volume_issues_parallel(100)

    @pytest.mark.asyncio
    async def test_parallel_pagination_count_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test validation of total count vs actual results."""
        client = _make_client(tmp_path)

        monkeypatch.setattr(client, "request", AsyncMock(return_value=_probe_response(250)))
        monkeypatch.setattr(
            client,
            "_fetch_single_page_issues",
            AsyncMock(side_effect=[_issue_rows(1, 1), _issue_rows(2, 2), _issue_rows(3, 3)]),
        )

        with pytest.raises(ComicVineError, match="Expected 250 issues but received 3"):
            await client._fetch_volume_issues_parallel(100)

    @pytest.mark.asyncio
    async def test_service_layer_parallel_optimization(self):
        """Test that service layer uses parallel requests when series_name is not provided."""
        mock_client = Mock()

        volume_response = ComicVineResponse(
            payload={
                "results": {
                    "id": 100,
                    "name": "Test Series",
                }
            },
            from_cache=False,
            cache_key="test_cache_key",
        )

        issues_response = [
            {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
            {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
        ]

        mock_client.fetch_volume = AsyncMock(return_value=volume_response)
        mock_client.fetch_volume_issues = AsyncMock(return_value=issues_response)

        result = await get_comicvine_series_issues(mock_client, 100, series_name="")

        mock_client.fetch_volume.assert_called_once_with(100)
        mock_client.fetch_volume_issues.assert_called_once_with(100)

        assert result.series_name == "Test Series"
        assert len(result.issues) == 2

    @pytest.mark.asyncio
    async def test_service_layer_with_pre_fetched_series_name(self):
        """Test that service layer uses single request when series_name is provided."""
        mock_client = Mock()

        issues_response = [
            {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
            {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100}},
        ]

        mock_client.fetch_volume_issues = AsyncMock(return_value=issues_response)

        result = await get_comicvine_series_issues(
            mock_client, 100, series_name="Pre-fetched Series"
        )

        mock_client.fetch_volume_issues.assert_called_once_with(100)
        mock_client.fetch_volume.assert_not_called()

        assert result.series_name == "Pre-fetched Series"
        assert len(result.issues) == 2

    @pytest.mark.asyncio
    async def test_volume_filter_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that volume filter validation works correctly."""
        client = _make_client(tmp_path)
        mixed_rows: list[dict[str, object]] = [
            {"id": 1, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}},
            {"id": 2, "issue_number": "2", "name": "Issue 2", "volume": {"id": 200}},
        ]

        # Mock the count probe response
        monkeypatch.setattr(client, "request", AsyncMock(return_value=_probe_response(2)))
        # Mock the page response with mixed volume data
        page_response = ComicVineResponse(
            payload={"number_of_total_results": 2, "results": mixed_rows},
            from_cache=False,
            cache_key="page_0",
        )
        # The second call to request is for the actual page fetch
        call_count = {"count": 0}
        
        async def mock_request(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                return _probe_response(2)
            return page_response
        
        monkeypatch.setattr(client, "request", mock_request)

        with pytest.raises(ComicVineError, match="ignored the requested volume filter"):
            await client._fetch_volume_issues_parallel(100)

    @pytest.mark.asyncio
    async def test_empty_results_handling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test handling of empty results."""
        client = _make_client(tmp_path)
        fetch_page = AsyncMock(return_value=[])
        monkeypatch.setattr(client, "request", AsyncMock(return_value=_probe_response(0)))
        monkeypatch.setattr(client, "_fetch_single_page_issues", fetch_page)

        result = await client._fetch_volume_issues_parallel(100)

        assert result == []
        fetch_page.assert_not_called()
