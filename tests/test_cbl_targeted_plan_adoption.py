"""Regression tests for explicit-target CBL adoption."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.shared_types import SourceBackedDecision
from app.services.cbl_plan_adoption import AdoptionCommitError, AdoptionMergeReport
from app.services.cbl_targeted_plan_adoption import adopt_cbl_into_existing_reading_plan


@dataclass
class _Plan:
    id: int = 42
    user_id: int = 7
    ordering_mode: str = "strict_sequential"
    lanes_json: list[dict[str, object]] = field(
        default_factory=lambda: [{"id": "main", "name": "Main", "order": 0}]
    )
    nodes_json: list[dict[str, object]] = field(default_factory=list)


@dataclass
class _Source:
    id: int = 9
    active: bool = True
    source_path: str = "Dark Horse/BPRD/Vol 3.cbl"
    content_hash: str = "hash"
    revision_sha: str = "rev"


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def scalar_one_or_none(self) -> object | None:
        return self.rows[0] if self.rows else None

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[object]:
        return self.rows


class _DB:
    def __init__(self, results: list[_Rows]) -> None:
        self.results = results
        self.index = 0
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _query: object) -> _Rows:
        result = self.results[self.index]
        self.index += 1
        return result

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _obj: object) -> None:
        return None


@pytest.mark.asyncio
async def test_adoption_mutates_exact_owned_plan() -> None:
    """CBL adoption must use the caller-selected plan, never discover/create another."""
    plan = _Plan()
    source = _Source()
    db = _DB([_Rows([plan]), _Rows([source]), _Rows([])])
    report = SimpleNamespace(entries=())
    merge_report = AdoptionMergeReport(reused_positions=[1])

    with (
        patch(
            "app.services.cbl_targeted_plan_adoption.reconcile_cbl_source_list",
            new_callable=AsyncMock,
            return_value=report,
        ),
        patch(
            "app.services.cbl_targeted_plan_adoption._merge_adopted_nodes",
            new_callable=AsyncMock,
            return_value=merge_report,
        ) as merge,
        patch(
            "app.services.cbl_targeted_plan_adoption.validate_node_ownership",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.cbl_targeted_plan_adoption.replace_compiled_rules",
            new_callable=AsyncMock,
        ),
    ):
        result = await adopt_cbl_into_existing_reading_plan(
            db,  # type: ignore[arg-type]
            user_id=7,
            plan_id=42,
            list_id=9,
            entry_decisions={1: SourceBackedDecision.INCLUDE},
            series_decisions={},
            client_content_hash="hash",
            client_revision_sha="rev",
        )

    assert result.plan is plan
    assert db.commits == 1
    assert merge.await_args is not None
    assert merge.await_args.args[1] is plan


@pytest.mark.asyncio
async def test_missing_target_plan_fails_without_creating_one() -> None:
    """A bad plan id fails closed rather than creating a source-specific plan."""
    db = _DB([_Rows([])])

    with pytest.raises(AdoptionCommitError, match="Reading Plan not found"):
        await adopt_cbl_into_existing_reading_plan(
            db,  # type: ignore[arg-type]
            user_id=7,
            plan_id=999,
            list_id=9,
            entry_decisions={},
            series_decisions={},
        )

    assert db.commits == 0
