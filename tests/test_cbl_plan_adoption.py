"""Tests for the canonical CBL adoption commit endpoint and service.

Covers the acceptance criteria in issue #2377 against the current implementation.
All tests use lightweight fakes to avoid requiring a live database.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.continuity_plan import ContinuityPlan
from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import (
    _resolve_decision,
    _verify_preview_fingerprint,
    adopt_cbl_material_into_reading_plan,
    AdoptionCommitError,
    AdoptionCommitResult,
    StalePreviewError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeEntry:
    """Lightweight stand-in for CBLSourceEntry used by merge/decision logic."""

    id: int
    position: int
    series_name: str
    volume_year: int | None = None


@dataclass
class _FakeCBLList:
    """Lightweight stand-in for CBLSourceList."""

    id: int
    source_path: str
    name: str
    content_hash: str
    revision_sha: str
    active: bool


@dataclass
class _FakePlan:
    """Lightweight stand-in for ContinuityPlan readable attributes."""

    id: int | None = None
    user_id: int = 1
    name: str = "plan"
    ordering_mode: str = "informational"
    nodes_json: list[dict[str, object]] = field(default_factory=list)
    lanes_json: list[dict[str, object]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _Rows:
    """Fake SQLAlchemy result sequence for scalar/scalars()."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return self._rows


class _FakeDB:
    """Minimal async DB stub for adoption-service tests."""

    def __init__(
        self,
        *,
        execute_results: list[_Rows] | None = None,
    ) -> None:
        self._execute_results: list[_Rows] = list(execute_results or [])
        self._call_count = 0
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(self, _query: object) -> _Rows:
        result = self._execute_results[self._call_count]
        self._call_count += 1
        return result

    async def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    async def refresh(self, _obj: object) -> None:
        pass


def _make_fact(
    *,
    position: int,
    cbl_entry_id: int | None = None,
    resolved_issue_id: int | None = None,
    resolution_status: str,
    series_name: str = "X",
    volume_year: int | None = None,
    comicvine_issue_id: str | None = None,
    external_series_identity_id: int | None = None,
) -> dict[str, object]:
    """Build a reconciliation fact dict matching the cbl_reconciliation schema."""
    return {
        "cbl_position": position,
        "series_name": series_name,
        "issue_number": f"#{position + 1}",
        "comicvine_issue_id": comicvine_issue_id,
        "external_series_identity_id": external_series_identity_id,
        "cbl_entry_id": position if cbl_entry_id is None else cbl_entry_id,
        "resolved_issue_id": resolved_issue_id,
        "resolution_status": resolution_status,
        "volume_year": volume_year,
    }


async def _adopt(
    db: _FakeDB,
    *,
    user_id: int = 1,
    list_id: int = 10,
    entries: list[_FakeEntry] | None = None,
    facts: list[dict[str, object]] | None = None,
    entry_decisions: dict[int, SourceBackedDecision] | None = None,
    series_decisions: dict[str, SourceBackedDecision] | None = None,
    series_overrides: dict[int, SourceBackedDecision] | None = None,
    existing_plan: _FakePlan | None = None,
    client_content_hash: str | None = None,
    client_revision_sha: str | None = None,
    cbl_list_content_hash: str = "hash",
    cbl_list_revision_sha: str = "rev",
    patch_writer: bool = True,
) -> AdoptionCommitResult:
    """Run adopt_cbl_material_into_reading_plan with mocked DB seams."""
    cbl_list = _FakeCBLList(
        id=list_id,
        source_path="/x.xml",
        name="X",
        content_hash=cbl_list_content_hash,
        revision_sha=cbl_list_revision_sha,
        active=True,
    )
    db._execute_results = [_Rows([cbl_list]), _Rows(entries or [])]
    report = MagicMock()
    report.entries = tuple(facts or [])

    patches = [
        patch(
            "app.services.cbl_plan_adoption.reconcile_cbl_source_list",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch(
            "app.services.cbl_plan_adoption._find_existing_adopted_plan",
            new_callable=AsyncMock,
            return_value=existing_plan,
        ),
        patch(
            "app.services.cbl_plan_adoption.validate_node_ownership",
            new_callable=AsyncMock,
        ),
    ]
    if patch_writer:
        patches.append(
            patch(
                "app.services.cbl_plan_adoption.replace_compiled_rules",
                new_callable=AsyncMock,
                return_value=True,
            )
        )
    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        result = await adopt_cbl_material_into_reading_plan(
            db,
            user_id=user_id,
            list_id=list_id,
            entry_decisions=entry_decisions or {},
            series_decisions=series_decisions or {},
            series_overrides=series_overrides,
            client_content_hash=client_content_hash,
            client_revision_sha=client_revision_sha,
        )
    return result


# ---------------------------------------------------------------------------
# _verify_preview_fingerprint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_content_hash_raises_stale_error() -> None:
    """Verify StalePreviewError is raised when content_hash mismatches."""
    cbl_list = _FakeCBLList(
        id=1, source_path="/a.xml", name="A",
        content_hash="correct", revision_sha="r", active=True,
    )
    with pytest.raises(StalePreviewError, match="Source fingerprint mismatch"):
        await _verify_preview_fingerprint(cbl_list, "wrong", "r")


@pytest.mark.asyncio
async def test_stale_revision_sha_raises_stale_error() -> None:
    """Verify StalePreviewError is raised when revision_sha mismatches."""
    cbl_list = _FakeCBLList(
        id=1, source_path="/a.xml", name="A",
        content_hash="h", revision_sha="correct", active=True,
    )
    with pytest.raises(StalePreviewError, match="Revision mismatch"):
        await _verify_preview_fingerprint(cbl_list, "h", "wrong")


@pytest.mark.asyncio
async def test_matching_fingerprint_passes() -> None:
    """Verify no error is raised when fingerprint matches exactly."""
    cbl_list = _FakeCBLList(
        id=1, source_path="/a.xml", name="A",
        content_hash="h", revision_sha="r", active=True,
    )
    await _verify_preview_fingerprint(cbl_list, "h", "r")


# ---------------------------------------------------------------------------
# _resolve_decision
# ---------------------------------------------------------------------------


def _entry(pos: int, series: str = "X") -> _FakeEntry:
    """Build a minimal fake entry for decision resolution."""
    return _FakeEntry(id=pos, position=pos, series_name=series)


def test_override_beats_entry_and_series() -> None:
    """An explicit override takes highest precedence over entry and series."""
    result = _resolve_decision(
        _entry(0),
        entry_decisions={0: SourceBackedDecision.EXCLUDE},
        series_overrides={0: SourceBackedDecision.INCLUDE},
        series_decisions={"X": SourceBackedDecision.EXCLUDE},
    )
    assert result == SourceBackedDecision.INCLUDE


def test_entry_beats_series_when_no_override() -> None:
    """Entry decision wins when no override is present for that position."""
    result = _resolve_decision(
        _entry(1),
        entry_decisions={1: SourceBackedDecision.EXCLUDE},
        series_overrides={},
        series_decisions={"X": SourceBackedDecision.INCLUDE},
    )
    assert result == SourceBackedDecision.EXCLUDE


def test_series_decision_applied_when_no_entry_or_override() -> None:
    """Series decision applies when there is no per-position decision."""
    result = _resolve_decision(
        _entry(2),
        entry_decisions={},
        series_overrides={},
        series_decisions={"X": SourceBackedDecision.EXCLUDE},
    )
    assert result == SourceBackedDecision.EXCLUDE


def test_none_returned_when_no_decisions() -> None:
    """None is returned when no decisions exist for the entry."""
    result = _resolve_decision(
        _entry(3),
        entry_decisions={},
        series_overrides={},
        series_decisions={},
    )
    assert result is None


# ---------------------------------------------------------------------------
# adopt_cbl_material_into_reading_plan – service integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_fingerprint_aborts_with_no_commit() -> None:
    """When fingerprint is stale the commit must never happen."""
    db = _FakeDB()
    cbl = _FakeCBLList(
        id=1, source_path="/x.xml", name="X",
        content_hash="current_hash",
        revision_sha="current_rev",
        active=True,
    )
    db._execute_results = [_Rows([cbl])]
    with patch(
        "app.services.cbl_plan_adoption.reconcile_cbl_source_list",
        new_callable=AsyncMock,
    ) as mock_reconcile:
        with pytest.raises(StalePreviewError):
            await adopt_cbl_material_into_reading_plan(
                db,
                user_id=1,
                list_id=1,
                entry_decisions={},
                series_decisions={},
                client_content_hash="stale_hash",
                client_revision_sha="current_rev",
            )
        mock_reconcile.assert_not_called()
    assert db.commit_count == 0


@pytest.mark.asyncio
async def test_list_not_found_raises_adoption_error() -> None:
    """AdoptionCommitError when the source list does not exist."""
    db = _FakeDB(execute_results=[_Rows([])])
    with pytest.raises(AdoptionCommitError, match="CBL source list not found"):
        await adopt_cbl_material_into_reading_plan(
            db, user_id=1, list_id=99,
            entry_decisions={}, series_decisions={},
        )


@pytest.mark.asyncio
async def test_inactive_list_raises_adoption_error() -> None:
    """AdoptionCommitError when the list exists but is inactive."""
    cbl = _FakeCBLList(
        id=1, source_path="/x.xml", name="X",
        content_hash="h", revision_sha="r", active=False,
    )
    db = _FakeDB(execute_results=[_Rows([cbl])])
    with pytest.raises(AdoptionCommitError, match="not active"):
        await adopt_cbl_material_into_reading_plan(
            db, user_id=1, list_id=1,
            entry_decisions={}, series_decisions={},
        )


@pytest.mark.asyncio
async def test_new_plan_created_when_no_existing_plan() -> None:
    """When no plan carries source provenance a new plan is created."""
    entry = _FakeEntry(id=10, position=0, series_name="X")
    fact = _make_fact(
        resolved_issue_id=100,
        resolution_status="existing",
        position=0,
        cbl_entry_id=10,
    )
    result = await _adopt(
        _FakeDB(),
        entries=[entry],
        facts=[fact],
        entry_decisions={0: SourceBackedDecision.INCLUDE},
    )
    plan = result.plan
    assert plan.id is None
    assert len(plan.nodes_json) == 1
    assert plan.nodes_json[0]["ref_id"] == 100
    assert result.reused_positions == [0]
    assert result.created_positions == []
    assert result.excluded_positions == []
    assert result.unresolved_positions == []


@pytest.mark.asyncio
async def test_existing_plan_reuses_nodes_with_provenance() -> None:
    """Existing plan node is reused and placement provenance is recorded."""
    existing = _FakePlan(
        id=5, user_id=1, name="CBL adoption",
        ordering_mode="informational",
        nodes_json=[{
            "id": "cbl-10",
            "node_type": "issue",
            "ref_id": 100,
            "lane_id": "default",
            "position": 0,
            "is_checkpoint": False,
            "convergence_gate": [],
            "source_cbl_placements": [],
        }],
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
    )
    entry = _FakeEntry(id=10, position=0, series_name="X")
    fact = _make_fact(
        resolved_issue_id=100,
        resolution_status="existing",
        position=0,
        cbl_entry_id=10,
    )

    result = await _adopt(
        _FakeDB(),
        existing_plan=existing,
        entries=[entry],
        facts=[fact],
        entry_decisions={0: SourceBackedDecision.INCLUDE},
    )
    plan = result.plan
    assert plan.id == 5
    assert len(plan.nodes_json) == 1
    placements = cast(
        list[dict[str, object]],
        plan.nodes_json[0]["source_cbl_placements"],
    )
    assert any(p.get("source_path") == "/x.xml" for p in placements)
    assert result.reused_positions == [0]


@pytest.mark.asyncio
async def test_approved_missing_issue_materialized_and_node_added() -> None:
    """Approved missing-importable entry should create an issue node."""
    entry = _FakeEntry(id=20, position=0, series_name="Y")
    fact = _make_fact(
        resolved_issue_id=None,
        resolution_status="no_owned_issue_for_comicvine_id",
        position=0,
        cbl_entry_id=20,
    )
    fake_issue = MagicMock()
    fake_issue.id = 200

    with patch(
        "app.services.cbl_plan_adoption._ensure_missing_issue_created",
        new_callable=AsyncMock,
        return_value=fake_issue,
    ):
        result = await _adopt(
            _FakeDB(),
            entries=[entry],
            facts=[fact],
            entry_decisions={0: SourceBackedDecision.INCLUDE},
        )

    plan = result.plan
    assert len(plan.nodes_json) == 1
    node = plan.nodes_json[0]
    assert node["ref_id"] == 200
    assert node["id"] == "cbl-20"
    assert result.created_positions == [0]
    assert result.reused_positions == []


@pytest.mark.asyncio
async def test_unapproved_missing_issue_not_materialized() -> None:
    """A missing entry without an explicit INCLUDE decision is not materialized."""
    entry = _FakeEntry(id=30, position=0, series_name="Z")
    fact = _make_fact(
        resolved_issue_id=None,
        resolution_status="no_owned_issue_for_comicvine_id",
        position=0,
        cbl_entry_id=30,
    )
    with patch(
        "app.services.cbl_plan_adoption._ensure_missing_issue_created",
        new_callable=AsyncMock,
    ) as mock_create:
        result = await _adopt(
            _FakeDB(),
            entries=[entry],
            facts=[fact],
            entry_decisions={},
        )
    mock_create.assert_not_called()
    plan = result.plan
    assert len(plan.nodes_json) == 0
    assert result.excluded_positions == [0]


@pytest.mark.asyncio
async def test_unresolved_entry_skipped_and_reported() -> None:
    """Unresolved entries are never adopted or guessed at."""
    entry = _FakeEntry(id=40, position=0, series_name="U")
    fact = _make_fact(
        resolved_issue_id=None,
        resolution_status="ambiguous_unresolved",
        position=0,
        cbl_entry_id=40,
    )
    with patch(
        "app.services.cbl_plan_adoption._ensure_missing_issue_created",
        new_callable=AsyncMock,
    ) as mock_create:
        result = await _adopt(
            _FakeDB(),
            entries=[entry],
            facts=[fact],
            entry_decisions={0: SourceBackedDecision.INCLUDE},
        )
    mock_create.assert_not_called()
    plan = result.plan
    assert len(plan.nodes_json) == 0
    assert result.unresolved_positions == [0]


@pytest.mark.asyncio
async def test_excluded_existing_entry_creates_no_node() -> None:
    """An explicitly excluded existing entry should not appear in the plan."""
    entry = _FakeEntry(id=50, position=0, series_name="E")
    fact = _make_fact(
        resolved_issue_id=500,
        resolution_status="existing",
        position=0,
        cbl_entry_id=50,
    )
    result = await _adopt(
        _FakeDB(),
        entries=[entry],
        facts=[fact],
        entry_decisions={0: SourceBackedDecision.EXCLUDE},
    )
    plan = result.plan
    assert len(plan.nodes_json) == 0
    assert result.excluded_positions == [0]


@pytest.mark.asyncio
async def test_override_includes_entry_despite_entry_exclude() -> None:
    """A series_override INCLUDE should force adoption even when entry is EXCLUDE."""
    entry = _FakeEntry(id=80, position=0, series_name="O")
    fact = _make_fact(
        resolved_issue_id=800,
        resolution_status="existing",
        position=0,
        cbl_entry_id=80,
    )
    result = await _adopt(
        _FakeDB(),
        entries=[entry],
        facts=[fact],
        entry_decisions={0: SourceBackedDecision.EXCLUDE},
        series_overrides={0: SourceBackedDecision.INCLUDE},
    )
    plan = result.plan
    assert len(plan.nodes_json) == 1
    assert plan.nodes_json[0]["ref_id"] == 800
    assert result.reused_positions == [0]


@pytest.mark.asyncio
async def test_replay_is_idempotent_no_duplicate_nodes() -> None:
    """Running merge twice produces no duplicate nodes or placements."""
    existing = _FakePlan(
        id=8, user_id=1, name="CBL idem",
        ordering_mode="informational",
        nodes_json=[{
            "id": "cbl-11",
            "node_type": "issue",
            "ref_id": 111,
            "lane_id": "default",
            "position": 0,
            "is_checkpoint": False,
            "convergence_gate": [],
            "source_cbl_placements": [
                {"source_path": "/x.xml", "position": 0},
            ],
        }],
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
    )
    entry = _FakeEntry(id=11, position=0, series_name="X")
    fact = _make_fact(
        resolved_issue_id=111,
        resolution_status="existing",
        position=0,
        cbl_entry_id=11,
    )
    result = await _adopt(
        _FakeDB(),
        existing_plan=existing,
        entries=[entry],
        facts=[fact],
        entry_decisions={0: SourceBackedDecision.INCLUDE},
    )
    plan = result.plan
    nodes = plan.nodes_json
    assert len(nodes) == 1
    placements = cast(
        list[dict[str, object]],
        nodes[0]["source_cbl_placements"],
    )
    paths = [p.get("source_path") for p in placements]
    assert paths.count("/x.xml") == 1
    assert result.reused_positions == [0]


@pytest.mark.asyncio
async def test_informational_plan_keeps_informational_ordering_mode() -> None:
    """Plan ordering_mode must not be mutated by adoption."""
    existing = _FakePlan(
        id=12, user_id=1, name="info",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
    )
    entry = _FakeEntry(id=60, position=0, series_name="I")
    fact = _make_fact(
        resolved_issue_id=600,
        resolution_status="existing",
        position=0,
        cbl_entry_id=60,
    )
    with patch(
        "app.services.cbl_plan_adoption.replace_compiled_rules",
        new_callable=AsyncMock,
    ) as mock_writer:
        result = await _adopt(
            _FakeDB(), existing_plan=existing,
            entries=[entry], facts=[fact],
            patch_writer=False,
        )
        mock_writer.assert_called_once()
        kw = mock_writer.call_args.kwargs
        assert kw["ordering_mode"] == "informational"
    assert result.plan.ordering_mode == "informational"


@pytest.mark.asyncio
async def test_strict_plan_passes_strict_ordering_mode_to_writer() -> None:
    """Existing strict_sequential plan preserves its ordering_mode."""
    existing = _FakePlan(
        id=13, user_id=1, name="strict",
        ordering_mode="strict_sequential",
        nodes_json=[{
            "id": "cbl-1",
            "node_type": "issue",
            "ref_id": 1,
            "lane_id": "default",
            "position": 0,
            "is_checkpoint": False,
            "convergence_gate": [],
        }],
        lanes_json=[{"id": "default", "name": "Default", "order": 0}],
    )
    entry = _FakeEntry(id=70, position=1, series_name="S")
    fact = _make_fact(
        resolved_issue_id=700,
        resolution_status="existing",
        position=1,
        cbl_entry_id=70,
    )
    with patch(
        "app.services.cbl_plan_adoption.replace_compiled_rules",
        new_callable=AsyncMock,
    ) as mock_writer:
        result = await _adopt(
            _FakeDB(), existing_plan=existing,
            entries=[entry], facts=[fact],
            patch_writer=False,
        )
        mock_writer.assert_called_once()
        kw = mock_writer.call_args.kwargs
        assert kw["ordering_mode"] == "strict_sequential"
    assert result.plan.ordering_mode == "strict_sequential"


@pytest.mark.asyncio
async def test_service_has_no_dependency_group_or_cbl_order_state() -> None:
    """The service module must not depend on DependencyGroup or cbl-order:* state."""
    import app.services.cbl_plan_adoption as svc_mod
    import app.models.continuity_plan as plan_mod

    assert not hasattr(svc_mod, "DependencyGroup")
    assert not hasattr(svc_mod, "Dependency")
    assert not hasattr(svc_mod, "DependencyGroupMembership")
    assert not hasattr(plan_mod, "cbl_order")

    db = _FakeDB()
    result = await _adopt(
        db,
        entries=[_FakeEntry(id=10, position=0, series_name="X")],
        facts=[_make_fact(
            resolved_issue_id=100,
            resolution_status="existing",
            position=0,
            cbl_entry_id=10,
        )],
        entry_decisions={0: SourceBackedDecision.INCLUDE},
    )
    assert result.plan is not None
    for added in db.added:
        assert not added.__class__.__name__.startswith("Dependency")
