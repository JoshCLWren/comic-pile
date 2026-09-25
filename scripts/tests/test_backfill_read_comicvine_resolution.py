"""Tests for ComicVine read-issue identity resolution logic."""
import pytest
from unittest.mock import AsyncMock, patch
from scripts.backfill_read_comicvine import (
    _title_search_hint,
    _resolve_provider_issue,
    ReadIssue,
)

@pytest.mark.parametrize("title, expected", [
    ("X-Men (1963)", ("X-Men", 1963)),
    ("X-Factor (Vol. 1) (1985 - 1998)", ("X-Factor (Vol. 1)", 1985)),
    ("Spider-Man", ("Spider-Man", None)),
    ("The Avengers (1963-present)", ("The Avengers", 1963)),
])
def test_title_search_hint(title, expected):
    """Test the title search hint extraction logic."""
    assert _title_search_hint(title) == expected

@pytest.mark.asyncio
async def test_resolve_provider_issue_unique_match():
    """Test resolution when exactly one provider issue matches."""
    db = AsyncMock()
    client = AsyncMock()
    
    issue = ReadIssue(
        issue_id=1, thread_id=1, thread_title="X-Men", issue_number="1", 
        position=1, identity_id=None, external_id=None, has_creator_credits=False,
        has_person_credit_source=False, creator_credit_count=0,
        series_identity_id=10, series_external_id="4050-10", 
        series_volume_id=100, series_name="X-Men", sibling_volume_ids=()
    )
    
    client.fetch_volume_issues.return_value = [
        {"id": 1001, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100, "name": "X-Men"}},
        {"id": 1002, "issue_number": "2", "name": "Issue 2", "volume": {"id": 100, "name": "X-Men"}},
    ]
    
    roster_cache = {}
    
    with patch("scripts.backfill_read_comicvine._persist_resolved_mapping", new_callable=AsyncMock) as mock_persist:
        mock_persist.return_value = (200, "1001")
        result = await _resolve_provider_issue(db, client, user_id=1, issue=issue, roster_cache=roster_cache)
        
        assert result == (200, "1001")
        mock_persist.assert_called_once()

@pytest.mark.asyncio
async def test_resolve_provider_issue_ambiguous_match():
    """Test resolution when multiple different provider issues match."""
    db = AsyncMock()
    client = AsyncMock()
    
    issue = ReadIssue(
        issue_id=1, thread_id=1, thread_title="X-Men", issue_number="1", 
        position=1, identity_id=None, external_id=None, has_creator_credits=False,
        has_person_credit_source=False, creator_credit_count=0,
        series_identity_id=10, series_external_id="4050-10", 
        series_volume_id=100, series_name="X-Men", sibling_volume_ids=(101,)
    )
    
    # Volume 100 has issue 1 (ID 1001), Volume 101 also has issue 1 (ID 1002)
    def side_effect(volume_id):
        if volume_id == 100:
            return [{"id": 1001, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}}]
        if volume_id == 101:
            return [{"id": 1002, "issue_number": "1", "name": "Issue 1", "volume": {"id": 101}}]
        return []
    
    client.fetch_volume_issues.side_effect = side_effect
    roster_cache = {}
    
    result = await _resolve_provider_issue(db, client, user_id=1, issue=issue, roster_cache=roster_cache)
    assert result is None

@pytest.mark.asyncio
async def test_resolve_provider_issue_same_identity_different_volumes():
    """Test resolution when multiple volumes point to the same provider issue."""
    db = AsyncMock()
    client = AsyncMock()
    
    issue = ReadIssue(
        issue_id=1, thread_id=1, thread_title="X-Men", issue_number="1", 
        position=1, identity_id=None, external_id=None, has_creator_credits=False,
        has_person_credit_source=False, creator_credit_count=0,
        series_identity_id=10, series_external_id="4050-10", 
        series_volume_id=100, series_name="X-Men", sibling_volume_ids=(101,)
    )
    
    # Both volumes point to the same provider issue ID 1001
    def side_effect(volume_id):
        if volume_id == 100:
            return [{"id": 1001, "issue_number": "1", "name": "Issue 1", "volume": {"id": 100}}]
        if volume_id == 101:
            return [{"id": 1001, "issue_number": "1", "name": "Issue 1", "volume": {"id": 101}}]
        return []
    
    client.fetch_volume_issues.side_effect = side_effect
    roster_cache = {}
    
    with patch("scripts.backfill_read_comicvine._persist_resolved_mapping", new_callable=AsyncMock) as mock_persist:
        mock_persist.return_value = (200, "1001")
        result = await _resolve_provider_issue(db, client, user_id=1, issue=issue, roster_cache=roster_cache)
        assert result == (200, "1001")
        mock_persist.assert_called_once()
