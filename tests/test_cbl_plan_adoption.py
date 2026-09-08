"""Tests for the canonical CBL adoption commit endpoint and service."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import (
    adopt_cbl_material_into_reading_plan,
    StalePreviewError,
)


class _Result:
    """Minimal SQLAlchemy result stub."""

    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeAdoptionPlan:
    """Lightweight stand-in for CBLAdoptionPlan with an entries tuple."""

    def __init__(self, entries):
        self.entries = tuple(entries)


@pytest.fixture
def mock_cbl_list():
    """Create a mock CBL source list row."""
    from app.models.cbl_reference import CBLSourceList

    return CBLSourceList(
        id=1,
        source_id=1,
        source_path="/mirror/cbl/bprd.xml",
        name="B.P.R.D.",
        declared_issue_count=2,
        content_hash="abc123",
        revision_sha="def456",
        active=True,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.fixture
def mock_db_session(mock_cbl_list):
    """Create a mock database session that returns the CBL list on query."""

    async def _execute(_query):
        return _Result(mock_cbl_list)

    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(side_effect=_execute)
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = AsyncMock()
    return db


@pytest.fixture
def mock_adoption_plan():
    """An adoption plan whose one entry is explicitly approved and adoptable."""
    return _FakeAdoptionPlan(
        [
            {
                "cbl_position": 0,
                "cbl_entry_id": 10,
                "series_name": "B.P.R.D.: Plague of Frogs",
                "issue_number": "1",
                "resolution_status": "no_owned_issue_for_comicvine_id",
                "adopted": True,
            }
        ]
    )


@pytest.fixture
def mock_existing_plan():
    """A ContinuityPlan that already carries CBL provenance for this source."""
    from app.models.continuity_plan import ContinuityPlan

    return ContinuityPlan(
        id=5,
        user_id=1,
        name="CBL adoption for /mirror/cbl/bprd.xml",
        ordering_mode="informational",
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
        nodes_json=[
            {
                "id": "cbl-10",
                "node_type": "issue",
                "ref_id": 100,
                "lane_id": "default",
                "position": 0,
                "is_checkpoint": False,
                "convergence_gate": [],
                "source_cbl_placements": [
                    {"source_path": "/mirror/cbl/bprd.xml", "position": 0}
                ],
            }
        ],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


@pytest.mark.asyncio
async def test_stale_fingerprint_aborts(mock_db_session, mock_adoption_plan):
    """When the client fingerprint is stale, the commit fails with no writes."""
    from app.models.cbl_reference import CBLSourceList

    stale_list = CBLSourceList(
        id=1,
        source_id=1,
        source_path="/mirror/cbl/bprd.xml",
        name="B.P.R.D.",
        content_hash="NEW_HASH",
        revision_sha="NEW_SHA",
        active=True,
    )

    async def _execute(_query):
        return _Result(stale_list)

    mock_db_session.execute = AsyncMock(side_effect=_execute)

    with patch(
        "app.services.cbl_plan_adoption.preview_cbl_adoption"
    ) as mock_preview:
        mock_preview.return_value = ({"entries": ()}, mock_adoption_plan)

        with pytest.raises(StalePreviewError, match="Source fingerprint mismatch"):
            await adopt_cbl_material_into_reading_plan(
                mock_db_session,
                user_id=1,
                list_id=1,
                entry_decisions={},
                series_decisions={},
                series_overrides={},
                client_content_hash="abc123",
                client_revision_sha="def456",
            )

        mock_db_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_adopt_into_existing_plan_reuses_nodes(
    mock_db_session, mock_adoption_plan, mock_existing_plan
):
    """Committing into an existing plan reuses nodes and does not duplicate."""
    from app.models.continuity_plan import ContinuityPlan

    with patch(
        "app.services.cbl_plan_adoption.preview_cbl_adoption"
    ) as mock_preview, patch(
        "app.services.cbl_plan_adoption._find_existing_adopted_plan"
    ) as mock_find, patch(
        "app.services.cbl_plan_adoption._create_plan_nodes_for_adopted_issues"
    ) as mock_create:

        mock_preview.return_value = ({"entries": ()}, mock_adoption_plan)
        mock_find.return_value = mock_existing_plan
        mock_create.return_value = (mock_existing_plan, {10: 100})

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=1,
            list_id=1,
            entry_decisions={0: SourceBackedDecision.INCLUDE},
            series_decisions={},
            series_overrides={},
        )

        assert plan.id == 5
        mock_find.assert_called_once_with(mock_db_session, 1, "/mirror/cbl/bprd.xml")
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_adopt_creates_new_plan_when_none_exists(
    mock_db_session, mock_adoption_plan
):
    """When no plan carries this source provenance, a new plan is created."""
    from app.models.continuity_plan import ContinuityPlan

    with patch(
        "app.services.cbl_plan_adoption.preview_cbl_adoption"
    ) as mock_preview, patch(
        "app.services.cbl_plan_adoption._find_existing_adopted_plan"
    ) as mock_find, patch(
        "app.services.cbl_plan_adoption._create_plan_nodes_for_adopted_issues"
    ) as mock_create:

        created = ContinuityPlan(
            id=9,
            user_id=1,
            name="CBL adoption for /mirror/cbl/bprd.xml",
            ordering_mode="informational",
            lanes_json=[{"id": "default", "name": "Default", "order": 0}],
            nodes_json=[{"id": "cbl-10", "ref_id": 100}],
        )

        mock_preview.return_value = ({"entries": ()}, mock_adoption_plan)
        mock_find.return_value = None
        mock_create.return_value = (created, {10: 100})

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=1,
            list_id=1,
            entry_decisions={0: SourceBackedDecision.INCLUDE},
            series_decisions={},
            series_overrides={},
        )

        assert plan.id == 9
        assert len(plan.nodes_json) == 1
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_unresolved_entries_are_not_materialized_into_nodes(
    mock_db_session,
):
    """Unresolved entries never become new issues or plan nodes."""
    plan_with_unresolved = _FakeAdoptionPlan(
        [
            {
                "cbl_position": 2,
                "cbl_entry_id": 12,
                "series_name": "Unresolved Series",
                "issue_number": "1",
                "resolution_status": "ambiguous_unresolved",
                "adopted": False,
            }
        ]
    )

    with patch(
        "app.services.cbl_plan_adoption.preview_cbl_adoption"
    ) as mock_preview, patch(
        "app.services.cbl_plan_adoption._find_existing_adopted_plan"
    ) as mock_find, patch(
        "app.services.cbl_plan_adoption._create_plan_nodes_for_adopted_issues"
    ) as mock_create:

        from app.models.continuity_plan import ContinuityPlan

        created = ContinuityPlan(
            id=3,
            user_id=1,
            name="CBL adoption for /mirror/cbl/bprd.xml",
            ordering_mode="informational",
            lanes_json=[{"id": "default", "name": "Default", "order": 0}],
            nodes_json=[],
        )

        mock_preview.return_value = (
            {"entries": ()},
            plan_with_unresolved,
        )
        mock_find.return_value = None
        mock_create.return_value = (created, {})

        plan = await adopt_cbl_material_into_reading_plan(
            mock_db_session,
            user_id=1,
            list_id=1,
            entry_decisions={2: SourceBackedDecision.INCLUDE},
            series_decisions={},
            series_overrides={},
        )

        # adoptable set contains no unresolved entry, so no node is created.
        mock_create.assert_called_once()
        assert 12 not in mock_create.call_args.kwargs["adoptable_entry_ids"]
        assert plan.id == 3
