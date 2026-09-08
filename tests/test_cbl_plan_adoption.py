"""Tests for the canonical CBL adoption commit endpoint."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cbl_plan_adoption import router
from app.schemas.cbl_adoption import CBLAdoptionCommitRequest, SeriesDecision
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import (
    adopt_cbl_material_into_reading_plan,
    StalePreviewError,
)


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_preview_response():
    """Create a mock preview response."""
    return {
        "total_positions": 5,
        "resolved_count": 2,
        "unresolved_count": 2,
        "ambiguous_count": 1,
        "duplicate_identity_groups": 0,
        "entries": [],
        "first_unread_position": None,
        "first_unread_entry": None,
        "source_list_id": 1,
        "source_path": "/path/to/cbl.json",
        "source_repository": "https://github.com/test/repo",
        "content_hash": "abc123",
        "revision_sha": "def456",
    }


@pytest.fixture
def mock_adopted_plan():
    """Create a mock adopted plan."""
    from app.models.continuity_plan import ContinuityPlan

    return ContinuityPlan(
        id=1,
        user_id=1,
        name="Test Plan",
        ordering_mode="informational",
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
        nodes_json=[
            {
                "id": "cbl-1",
                "node_type": "issue",
                "ref_id": 100,
                "lane_id": "default",
                "position": 0,
                "is_checkpoint": False,
                "convergence_gate": [],
                "source_cbl_placement": {
                    "cbl_entry_id": 1,
                    "position": 0,
                },
            }
        ],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_adopt_cbl_material_success(
    mock_db_session,
    mock_preview_response,
    mock_adopted_plan,
):
    """Test successful adoption of CBL material into a Reading Plan."""
    list_id = 1
    user_id = 1

    request = CBLAdoptionCommitRequest(
        entry_decisions={0: SourceBackedDecision.INCLUDE, 1: SourceBackedDecision.EXCLUDE},
        series_decisions=[SeriesDecision(series_name="Test Series", decision=SourceBackedDecision.INCLUDE)],
        series_overrides=[],
    )

    with patch("app.services.cbl_plan_adoption.preview_cbl_adoption") as mock_preview, \
         patch("app.services.cbl_plan_adoption._verify_preview_fingerprint") as mock_verify, \
         patch("app.services.cbl_plan_adoption._find_existing_adopted_plan") as mock_find_plan:

        mock_preview.return_value = (mock_preview_response, mock_adopted_plan)
        mock_find_plan.return_value = None

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=user_id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions={s.series_name: s.decision for s in request.series_decisions},
            series_overrides={s.series_name: {p.cbl_position: p.decision for p in request.series_overrides} for s in request.series_decisions},
        )

        assert plan.id == 1
        assert plan.name == "Test Plan"
        assert len(plan.nodes_json) == 1
        assert plan.nodes_json[0]["id"] == "cbl-1"

        mock_preview.assert_called_once()
        mock_verify.assert_called_once()
        mock_find_plan.assert_called_once_with(mock_db_session, user_id, list_id)


@pytest.mark.asyncio
async def test_adopt_cbl_material_stale_preview(
    mock_db_session,
    mock_preview_response,
):
    """Test adoption with stale preview fingerprint."""
    list_id = 1
    user_id = 1

    with patch("app.services.cbl_plan_adoption.preview_cbl_adoption") as mock_preview:
        mock_preview.return_value = (mock_preview_response, {})

        from app.services.cbl_plan_adoption import adopt_cbl_material_into_reading_plan

        with pytest.raises(StalePreviewError, match="Source fingerprint mismatch"):
            await adopt_cbl_material_into_reading_plan(
                mock_db_session,
                user_id=user_id,
                list_id=list_id,
                entry_decisions={},
                series_decisions={},
                series_overrides={},
            )


@pytest.mark.asyncio
async def test_adopt_cbl_material_existing_plan(
    mock_db_session,
    mock_preview_response,
    mock_adopted_plan,
):
    """Test adoption with an existing plan."""
    list_id = 1
    user_id = 1

    request = CBLAdoptionCommitRequest(
        entry_decisions={0: SourceBackedDecision.INCLUDE},
        series_decisions=[],
        series_overrides=[],
    )

    with patch("app.services.cbl_plan_adoption.preview_cbl_adoption") as mock_preview, \
         patch("app.services.cbl_plan_adoption._verify_preview_fingerprint") as mock_verify, \
         patch("app.services.cbl_plan_adoption._find_existing_adopted_plan") as mock_find_plan:

        mock_preview.return_value = (mock_preview_response, mock_adopted_plan)
        mock_find_plan.return_value = mock_adopted_plan

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=user_id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions={},
            series_overrides={},
        )

        assert plan.id == 1
        mock_find_plan.assert_called_once_with(mock_db_session, user_id, list_id)


@pytest.mark.asyncio
async def test_adopt_cbl_material_duplicate_nodes(
    mock_db_session,
    mock_preview_response,
    mock_adopted_plan,
):
    """Test adoption that would create duplicate plan nodes."""
    list_id = 1
    user_id = 1

    mock_adopted_plan.nodes_json = [
        {
            "id": "cbl-1",
            "node_type": "issue",
            "ref_id": 100,
            "lane_id": "default",
            "position": 0,
            "is_checkpoint": False,
            "convergence_gate": [],
            "source_cbl_placement": {
                "cbl_entry_id": 1,
                "position": 0,
            },
        }
    ]

    request = CBLAdoptionCommitRequest(
        entry_decisions={0: SourceBackedDecision.INCLUDE},
        series_decisions=[],
        series_overrides=[],
    )

    with patch("app.services.cbl_plan_adoption.preview_cbl_adoption") as mock_preview, \
         patch("app.services.cbl_plan_adoption._verify_preview_fingerprint") as mock_verify, \
         patch("app.services.cbl_plan_adoption._find_existing_adopted_plan") as mock_find_plan:

        mock_preview.return_value = (mock_preview_response, mock_adopted_plan)
        mock_find_plan.return_value = mock_adopted_plan

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=user_id,
            list_id=list_id,
            entry_decisions=request.entry_decisions,
            series_decisions={},
            series_overrides={},
        )

        assert plan.id == 1
        assert len(plan.nodes_json) == 1
