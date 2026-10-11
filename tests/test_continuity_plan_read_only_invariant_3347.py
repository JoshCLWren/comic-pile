"""Read/write invariant decoupling for continuity plans (#3347).

Fix: ``ContinuityPlanResponse`` no longer inherits from
``ContinuityPlanWrite``. Both now share a plain fields-only base
``ContinuityPlanRead``; only ``ContinuityPlanWrite`` runs
``validate_structure``. The read path therefore never re-runs the
#3037 write invariant ("an issue may appear at most once in a plan"),
so legacy plans whose ``nodes_json`` contains the same issue twice load
without a 500, while writes remain gated at 422.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import (
    ContinuityPlanLane,
    ContinuityPlanNode,
    ContinuityPlanRead,
    ContinuityPlanResponse,
    ContinuityPlanWrite,
)
from app.schemas.cbl_adoption import CBLAdoptionCommitResponse
from app.schemas.custom_cbl import CustomCBLApplyResponse
from tests.conftest import get_or_create_user_async


def _lane() -> ContinuityPlanLane:
    return ContinuityPlanLane(id="main", name="Main", order=0)


def _node(node_id: str, ref_id: int, position: int, node_type: str = "issue") -> ContinuityPlanNode:
    return ContinuityPlanNode(
        id=node_id,
        node_type=node_type,
        ref_id=ref_id,
        lane_id="main",
        position=position,
    )


def _to_plan_response_from_production(source: str) -> object:
    """Load the real ``_to_plan_response`` function body from app/services/continuity.py.

    This execs the production function text into a namespace wired to the
    imported ``ContinuityPlanResponse``, exercising the exact function body
    that runs on every ``GET /continuity-plans/{id}`` rather than a copy.
    """
    path = pathlib.Path(source)
    text = path.read_text()
    start = text.index("def _to_plan_response")
    # Find the next top-level class definition after the function, or EOF.
    rest = text[start + len("def _to_plan_response") :]
    next_class = len(text)
    for match in __import__("re").finditer(r"\nclass \w+", rest):
        next_class = start + len("def _to_plan_response") + match.start()
        break
    body = text[start:next_class]
    namespace = {"ContinuityPlanResponse": ContinuityPlanResponse, "ContinuityPlan": type("ContinuityPlan", (), {})}
    exec(body, namespace)
    return namespace["_to_plan_response"]


def _read_response_fn() -> object:
    """Read-response constructor identical to app/services/continuity.py:_to_plan_response."""
    return _to_plan_response_from_production("app/services/continuity.py")


class TestReadInvariantIsWriteOnly:
    """Schema-level proof that read paths never run the duplicate-issue invariant."""

    def test_write_rejects_duplicate_issue_refs(self) -> None:
        """ContinuityPlanWrite still rejects repeated canonical issues (422 at the API)."""
        with pytest.raises(ValueError, match="an issue may appear at most once in a plan"):
            ContinuityPlanWrite(
                name="Dup",
                ordering_mode="informational",
                lanes=[_lane()],
                nodes=[_node("a", 1, 0), _node("b", 1, 1)],
            )
        # Distinct issues remain valid; repeated non-issue refs are not membership.
        ContinuityPlanWrite(
            name="Ok",
            ordering_mode="informational",
            lanes=[_lane()],
            nodes=[
                _node("a", 1, 0),
                _node("b", 2, 1),
                _node("c", 1, 2, node_type="thread"),
            ],
        )

    def test_response_neutralizes_duplicate_issue_refs_in_nodes_json(self) -> None:
        """ContinuityPlanResponse accepts legacy nodes_json containing duplicate ref_ids.

        This is the #3347 case: historical plans were written before #3037, so their
        nodes_json may contain the same issue twice. _to_plan_response builds a
        ContinuityPlanResponse from that raw JSON, and it must not raise.
        """
        legacy_nodes_json = [
            _node("a", 1, 0).model_dump(),
            _node("b", 1, 1).model_dump(),  # same ref_id as 'a'
        ]
        response = ContinuityPlanResponse(
            id=5,
            user_id=42,
            name="Legacy plan",
            ordering_mode="informational",
            lanes=[_lane().model_dump()],
            nodes=legacy_nodes_json,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert [node.ref_id for node in response.nodes] == [1, 1]

    def test_response_does_not_dedup_nodes(self) -> None:
        """Response preserves all legacy nodes verbatim instead of silently deduping."""
        legacy_nodes_json = [
            _node("a", 1, 0).model_dump(),
            _node("b", 1, 1).model_dump(),
        ]
        response = ContinuityPlanResponse(
            id=5,
            user_id=42,
            name="Legacy plan",
            ordering_mode="informational",
            lanes=[_lane().model_dump()],
            nodes=legacy_nodes_json,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert len(response.nodes) == 2
        assert len({node.id for node in response.nodes}) == 2

    def test_other_write_invariants_still_run(self) -> None:
        """Lane/node-id/position validations still guard writes after the refactor."""
        with pytest.raises(ValueError, match="lane ids must be unique"):
            ContinuityPlanWrite(
                name="Bad",
                ordering_mode="informational",
                lanes=[{"id": "a", "name": "A", "order": 0}, {"id": "a", "name": "A", "order": 1}],
                nodes=[],
            )
        with pytest.raises(ValueError, match="node ids must be unique"):
            ContinuityPlanWrite(
                name="Bad",
                ordering_mode="informational",
                lanes=[_lane()],
                nodes=[_node("a", 1, 0), _node("a", 2, 1)],
            )

    def test_field_parity_between_read_and_write(self) -> None:
        """ContinuityPlanRead exposes the shared fields; response adds identifiers."""
        assert set(ContinuityPlanRead.model_fields) == {"name", "ordering_mode", "lanes", "nodes"}
        assert set(ContinuityPlanResponse.model_fields) == {
            "name",
            "ordering_mode",
            "lanes",
            "nodes",
            "id",
            "user_id",
            "created_at",
            "updated_at",
        }


class TestResponseFromProductionPath:
    """Regression: the actual _to_plan_response body handles legacy duplicates."""

    def test_service_constructor_handles_duplicate_issue_refs(self) -> None:
        """The live _to_plan_response body must not raise on legacy nodes_json duplicates.

        This is the exact #3347 failure path: the service converts raw
        continuity_plans.nodes_json into a response, and legacy data can contain
        the same issue twice.
        """
        to_plan_response = cast(Callable[[Any], ContinuityPlanResponse], _read_response_fn())
        raw_lanes = [{"id": "main", "name": "Main", "order": 0}]
        raw_nodes = [
            {"id": "a", "node_type": "issue", "ref_id": 1, "lane_id": "main", "position": 0},
            {"id": "b", "node_type": "issue", "ref_id": 1, "lane_id": "main", "position": 1},
        ]
        plan_like = type("Plan", (), {
            "id": 5,
            "user_id": 42,
            "name": "Legacy plan",
            "ordering_mode": "informational",
            "lanes_json": raw_lanes,
            "nodes_json": raw_nodes,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        })()
        response = to_plan_response(plan_like)  # type: ignore[arg-type]
        assert response.id == 5
        assert [node.ref_id for node in response.nodes] == [1, 1]
        assert response.name == "Legacy plan"


class TestSubclassesReadLegacyData:
    """ContinuityPlanResponse subclasses must also degrade gracefully on reads."""

    def test_custom_cbl_apply_response_reads_duplicate_legacy_nodes(self) -> None:
        """CustomCBLApplyResponse inherits the read-only base and tolerates legacy duplicates."""
        legacy_nodes_json = [
            _node("a", 1, 0).model_dump(),
            _node("b", 1, 1).model_dump(),
        ]
        response = CustomCBLApplyResponse(
            id=5,
            user_id=42,
            name="Plan",
            ordering_mode="informational",
            lanes=[_lane().model_dump()],
            nodes=legacy_nodes_json,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            added_issue_ids=[3],
            skipped_existing_issue_ids=[1],
        )
        assert [node.ref_id for node in response.nodes] == [1, 1]

    def test_cbl_adoption_commit_response_reads_duplicate_legacy_nodes(self) -> None:
        """CBLAdoptionCommitResponse inherits the read-only base and tolerates legacy duplicates."""
        legacy_nodes_json = [
            _node("a", 1, 0).model_dump(),
            _node("b", 1, 1).model_dump(),
        ]
        response = CBLAdoptionCommitResponse(
            id=5,
            user_id=42,
            name="Plan",
            ordering_mode="informational",
            lanes=[_lane().model_dump()],
            nodes=legacy_nodes_json,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert [node.ref_id for node in response.nodes] == [1, 1]


class TestLegacyPlanReads:
    """API-level proof that legacy plans with duplicate issue refs no longer 500."""

    async def test_api_get_legacy_plan_with_duplicate_issue_refs_returns_200(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """GET /continuity-plans/{id} on legacy nodes_json with duplicate ref_ids -> 200.

        This is the exact #3347 reproduction: a plan persisted before #3037's
        migration carries the same issue twice in nodes_json. The GET response
        path builds ContinuityPlanResponse from that raw JSON; it must return
        200 with both legacy nodes intact rather than raising ValueError -> 500.
        """
        user = await get_or_create_user_async(async_db)
        issue = await self._make_issue(async_db, user_id=user.id, title="legacy duplicate")
        await async_db.commit()

        # Bypass the write invariant and inject duplicate nodes like #3037 left behind.
        raw_nodes = [
            _node("a", issue.id, 0).model_dump(),
            _node("b", issue.id, 1).model_dump(),  # duplicate ref_id
        ]
        await async_db.execute(
            insert(ContinuityPlan).values(
                user_id=user.id,
                name="Legacy plan (pre-#3037)",
                ordering_mode="informational",
                lanes_json=[_lane().model_dump()],
                nodes_json=raw_nodes,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await async_db.flush()

        plan = (
            await async_db.execute(
                select(ContinuityPlan).where(ContinuityPlan.user_id == user.id)
            )
        ).scalar_one()
        await async_db.commit()

        response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == plan.id
        assert body["name"] == "Legacy plan (pre-#3037)"
        # Both legacy nodes round-trip; the response does not dedup on the read path.
        assert [node["ref_id"] for node in body["nodes"]] == [issue.id, issue.id]
        assert len(body["nodes"]) == 2

    async def test_api_create_still_rejects_new_duplicate_issues(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """POST /continuity-plans/ with duplicate issue refs still returns 422."""
        user = await get_or_create_user_async(async_db)
        issue_a = await self._make_issue(async_db, user_id=user.id, title="a")
        issue_b = await self._make_issue(async_db, user_id=user.id, title="b")
        await async_db.commit()

        payload = {
            "name": "Dup plan",
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [
                {"id": "n1", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 0},
                {"id": "n2", "node_type": "issue", "ref_id": issue_b.id, "lane_id": "main", "position": 1},
                {"id": "n3", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 2},
            ],
        }
        response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
        assert response.status_code == 422, response.text
        assert "an issue may appear at most once in a plan" in response.text

    async def test_api_update_still_rejects_new_duplicate_issues(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """PUT /continuity-plans/{id} with duplicate issue refs still returns 422."""
        user = await get_or_create_user_async(async_db)
        issue_a = await self._make_issue(async_db, user_id=user.id, title="a")
        issue_b = await self._make_issue(async_db, user_id=user.id, title="b")
        await async_db.commit()

        payload = {
            "name": "Clean plan",
            "ordering_mode": "informational",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [
                {"id": "n1", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 0},
                {"id": "n2", "node_type": "issue", "ref_id": issue_b.id, "lane_id": "main", "position": 1},
            ],
        }
        created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
        assert created.status_code == 201, created.text
        plan_id = created.json()["id"]

        payload["nodes"].append(
            {"id": "n3", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 2}
        )
        updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
        assert updated.status_code == 422, updated.text
        assert "an issue may appear at most once in a plan" in updated.text

    @staticmethod
    async def _make_issue(async_db: AsyncSession, *, user_id: int, title: str) -> Issue:
        """Create one owned issue for continuity-plan tests."""
        thread = Thread(
            title=title,
            format="comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=user_id,
            total_issues=1,
            reading_progress="unstarted",
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        await async_db.flush()
        issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
        async_db.add(issue)
        await async_db.flush()
        return issue

    @staticmethod
    async def _legacy_plan_with_duplicates(
        async_db: AsyncSession, *, user_id: int, ref_ids: list[int]
    ) -> int:
        """Insert a continuity plan whose nodes_json contains duplicate issue refs."""
        raw_nodes = [
            _node(f"n{i}", ref_ids[i % len(ref_ids)], i).model_dump()
            for i in range(len(ref_ids))
        ]
        await async_db.execute(
            insert(ContinuityPlan).values(
                user_id=user_id,
                name="legacy",
                ordering_mode="informational",
                lanes_json=[_lane().model_dump()],
                nodes_json=raw_nodes,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await async_db.flush()
        plan = (
            await async_db.execute(
                select(ContinuityPlan).where(ContinuityPlan.user_id == user_id).order_by(ContinuityPlan.id)
            )
        ).scalar_one()
        return plan.id


class TestLegacyPlanReadsRoundTrip:
    """Multiple duplicates and mixed node types survive read without 500."""

    @staticmethod
    async def _legacy_plan_with_duplicates(
        async_db: AsyncSession, *, user_id: int, ref_ids: list[int]
    ) -> int:
        """Insert a continuity plan whose nodes_json contains duplicate issue refs."""
        raw_nodes = [
            _node(f"n{i}", ref_ids[i % len(ref_ids)], i).model_dump()
            for i in range(len(ref_ids))
        ]
        await async_db.execute(
            insert(ContinuityPlan).values(
                user_id=user_id,
                name="legacy",
                ordering_mode="informational",
                lanes_json=[_lane().model_dump()],
                nodes_json=raw_nodes,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await async_db.flush()
        plan = (
            await async_db.execute(
                select(ContinuityPlan).where(ContinuityPlan.user_id == user_id).order_by(ContinuityPlan.id)
            )
        ).scalar_one()
        return plan.id

    async def test_multi_duplicate_issue_refs_read_cleanly(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """A plan referencing the same issue four times round-trips intact on GET."""
        user = await get_or_create_user_async(async_db)
        issue = await self._make_issue(async_db, user_id=user.id, title="multi-dup")
        await async_db.commit()
        plan_id = await self._legacy_plan_with_duplicates(async_db, user_id=user.id, ref_ids=[issue.id] * 4)
        await async_db.commit()

        response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["nodes"]) == 4
        assert all(node["ref_id"] == issue.id for node in body["nodes"])

    async def test_mixed_duplicate_and_unique_issue_refs_read_cleanly(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Duplicates coexisting with unique issues and thread nodes round-trip."""
        user = await get_or_create_user_async(async_db)
        issue_a = await self._make_issue(async_db, user_id=user.id, title="a")
        issue_b = await self._make_issue(async_db, user_id=user.id, title="b")
        await async_db.commit()
        plan_id = await self._legacy_plan_with_duplicates(async_db, user_id=user.id, ref_ids=[issue_a.id, issue_b.id, issue_a.id])
        await async_db.commit()

        response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert [node["ref_id"] for node in body["nodes"]] == [issue_a.id, issue_b.id, issue_a.id]

    @staticmethod
    async def _make_issue(async_db: AsyncSession, *, user_id: int, title: str) -> Issue:
        """Create one owned issue for continuity-plan tests."""
        thread = Thread(
            title=title,
            format="comic",
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=user_id,
            total_issues=1,
            reading_progress="unstarted",
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        await async_db.flush()
        issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
        async_db.add(issue)
        await async_db.flush()
        return issue
