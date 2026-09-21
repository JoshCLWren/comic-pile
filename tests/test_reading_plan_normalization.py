"""Normalized Reading Plan persistence around canonical Issues and Dependencies.

Covers the Chunk 1 acceptance contract from issue #2551 without changing
Roll eligibility behavior:

- two plans can reference the same Issue and the same Dependency;
- editing or deleting one plan preserves the other's shared references;
- convergence is multiple incoming canonical Dependencies, not a
  ContinuityRule primitive;
- Issue read state stays global across overlapping plans;
- existing plans are readable through the normalized representation with
  source/provenance preserved.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import (
    ReadingPlanDependency,
    ReadingPlanIssue,
)
from app.models.thread import Thread
from app.repositories import reading_plan_repository
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services import reading_plan_normalization
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned issue for reading-plan normalization tests."""
    thread = Thread(
        title=f"Normalized plan {suffix}",
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


def _node(
    occurrence_id: str,
    issue_id: int,
    position: int,
    *,
    lane_id: str = "main",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one issue plan node payload with optional provenance fields."""
    node: dict[str, object] = {
        "id": occurrence_id,
        "node_type": "issue",
        "ref_id": issue_id,
        "lane_id": lane_id,
        "position": position,
    }
    if extra:
        node.update(extra)
    return node


def _plan_payload(name: str, nodes: list[dict[str, object]]) -> dict[str, object]:
    """Build a one-lane informational plan payload."""
    return {
        "name": name,
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": nodes,
    }


async def _make_dependency(
    async_db: AsyncSession, *, source_id: int, target_id: int
) -> Dependency:
    """Persist one canonical Dependency edge for normalization tests."""
    dependency = Dependency(source_issue_id=source_id, target_issue_id=target_id)
    async_db.add(dependency)
    await async_db.flush()
    return dependency


async def _create_plan(
    auth_client: AsyncClient, name: str, nodes: list[dict[str, object]]
) -> int:
    """Create one plan through the API and return its ID."""
    response = await auth_client.post(
        "/api/v1/continuity-plans/", json=_plan_payload(name, nodes)
    )
    assert response.status_code == 201, response.text
    plan_id = response.json()["id"]
    assert isinstance(plan_id, int)
    return plan_id


@pytest.mark.asyncio
async def test_two_plans_can_reference_the_same_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """One Issue may belong to multiple Reading Plans with separate context."""
    user = await get_or_create_user_async(async_db)
    shared = await _make_issue(async_db, user_id=user.id, suffix="shared")
    only_p = await _make_issue(async_db, user_id=user.id, suffix="only-p")
    only_q = await _make_issue(async_db, user_id=user.id, suffix="only-q")
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client,
        "Plan P",
        [_node("p-shared", shared.id, 0), _node("p-only", only_p.id, 1)],
    )
    plan_q = await _create_plan(
        auth_client,
        "Plan Q",
        [_node("q-shared", shared.id, 0), _node("q-only", only_q.id, 1)],
    )

    membership_p = await auth_client.get(f"/api/v1/continuity-plans/{plan_p}/membership")
    membership_q = await auth_client.get(f"/api/v1/continuity-plans/{plan_q}/membership")
    assert membership_p.status_code == 200, membership_p.text
    assert membership_q.status_code == 200, membership_q.text
    assert {row["issue_id"] for row in membership_p.json()["issues"]} == {
        shared.id,
        only_p.id,
    }
    assert {row["issue_id"] for row in membership_q.json()["issues"]} == {
        shared.id,
        only_q.id,
    }

    containing = await reading_plan_repository.plans_containing_issue(
        async_db, issue_id=shared.id
    )
    assert containing == sorted([plan_p, plan_q])


@pytest.mark.asyncio
async def test_two_plans_can_reference_the_same_dependency(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """One canonical Dependency may be referenced by multiple plans."""
    user = await get_or_create_user_async(async_db)
    source = await _make_issue(async_db, user_id=user.id, suffix="dep-source")
    target = await _make_issue(async_db, user_id=user.id, suffix="dep-target")
    await async_db.commit()
    dependency = await _make_dependency(
        async_db, source_id=source.id, target_id=target.id
    )
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client, "Plan P", [_node("p-target", target.id, 0)]
    )
    plan_q = await _create_plan(
        auth_client, "Plan Q", [_node("q-target", target.id, 0)]
    )

    for plan_id in (plan_p, plan_q):
        linked = await auth_client.post(
            f"/api/v1/continuity-plans/{plan_id}/dependencies/{dependency.id}",
            json={"explanation": "Starman gates JSA"},
        )
        assert linked.status_code == 201, linked.text
        body = linked.json()
        assert body["dependency_id"] == dependency.id
        assert body["source_issue_id"] == source.id
        assert body["target_issue_id"] == target.id

    # Linking twice is idempotent, not a second executable edge.
    repeated = await auth_client.post(
        f"/api/v1/continuity-plans/{plan_p}/dependencies/{dependency.id}",
        json={},
    )
    assert repeated.status_code == 201, repeated.text
    edges = (
        await async_db.execute(select(Dependency).where(Dependency.id == dependency.id))
    ).scalars().all()
    assert len(edges) == 1

    referencing = await reading_plan_repository.plans_referencing_dependency(
        async_db, dependency_id=dependency.id
    )
    assert referencing == sorted([plan_p, plan_q])


@pytest.mark.asyncio
async def test_deleting_one_plan_preserves_shared_references(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Plan deletion cascades only to plan-local rows, never shared targets."""
    user = await get_or_create_user_async(async_db)
    shared = await _make_issue(async_db, user_id=user.id, suffix="shared")
    target = await _make_issue(async_db, user_id=user.id, suffix="target")
    await async_db.commit()
    dependency = await _make_dependency(
        async_db, source_id=shared.id, target_id=target.id
    )
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client, "Plan P", [_node("p-shared", shared.id, 0)]
    )
    plan_q = await _create_plan(
        auth_client, "Plan Q", [_node("q-shared", shared.id, 0)]
    )
    for plan_id in (plan_p, plan_q):
        linked = await auth_client.post(
            f"/api/v1/continuity-plans/{plan_id}/dependencies/{dependency.id}", json={}
        )
        assert linked.status_code == 201, linked.text

    deleted = await auth_client.delete(f"/api/v1/continuity-plans/{plan_p}")
    assert deleted.status_code == 204, deleted.text

    # Shared Issue and canonical edge survive; the surviving plan keeps both.
    assert await async_db.get(Issue, shared.id) is not None
    assert await async_db.get(Dependency, dependency.id) is not None
    remaining_links = await reading_plan_repository.list_plan_dependencies(
        async_db, plan_id=plan_q
    )
    assert [link.dependency_id for link in remaining_links] == [dependency.id]
    remaining_issues = await reading_plan_repository.list_plan_issues(
        async_db, plan_id=plan_q
    )
    assert [row.issue_id for row in remaining_issues] == [shared.id]
    orphan_links = await reading_plan_repository.list_plan_dependencies(
        async_db, plan_id=plan_p
    )
    assert orphan_links == []


@pytest.mark.asyncio
async def test_editing_one_plan_preserves_other_plan_and_own_links(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Membership rebuild touches only the saved plan's issue/provenance rows."""
    user = await get_or_create_user_async(async_db)
    shared = await _make_issue(async_db, user_id=user.id, suffix="shared")
    replacement = await _make_issue(async_db, user_id=user.id, suffix="replacement")
    target = await _make_issue(async_db, user_id=user.id, suffix="target")
    await async_db.commit()
    dependency = await _make_dependency(
        async_db, source_id=shared.id, target_id=target.id
    )
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client, "Plan P", [_node("p-shared", shared.id, 0)]
    )
    plan_q = await _create_plan(
        auth_client, "Plan Q", [_node("q-shared", shared.id, 0)]
    )
    linked = await auth_client.post(
        f"/api/v1/continuity-plans/{plan_p}/dependencies/{dependency.id}", json={}
    )
    assert linked.status_code == 201, linked.text

    updated = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_p}",
        json=_plan_payload("Plan P", [_node("p-new", replacement.id, 0)]),
    )
    assert updated.status_code == 200, updated.text

    membership_p = await auth_client.get(f"/api/v1/continuity-plans/{plan_p}/membership")
    membership_q = await auth_client.get(f"/api/v1/continuity-plans/{plan_q}/membership")
    assert {row["issue_id"] for row in membership_p.json()["issues"]} == {replacement.id}
    assert {row["issue_id"] for row in membership_q.json()["issues"]} == {shared.id}
    # Editing membership never drops the plan's own dependency provenance.
    assert [link["dependency_id"] for link in membership_p.json()["dependencies"]] == [
        dependency.id
    ]


@pytest.mark.asyncio
async def test_convergence_is_multiple_incoming_dependencies(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Two prerequisites block one target through linked edges, no rule object."""
    user = await get_or_create_user_async(async_db)
    prereq_b = await _make_issue(async_db, user_id=user.id, suffix="prereq-b")
    prereq_c = await _make_issue(async_db, user_id=user.id, suffix="prereq-c")
    target_d = await _make_issue(async_db, user_id=user.id, suffix="target-d")
    await async_db.commit()
    edge_bd = await _make_dependency(
        async_db, source_id=prereq_b.id, target_id=target_d.id
    )
    edge_cd = await _make_dependency(
        async_db, source_id=prereq_c.id, target_id=target_d.id
    )
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client, "Convergence", [_node("p-target", target_d.id, 0)]
    )
    for edge in (edge_bd, edge_cd):
        linked = await auth_client.post(
            f"/api/v1/continuity-plans/{plan_p}/dependencies/{edge.id}", json={}
        )
        assert linked.status_code == 201, linked.text

    membership = await auth_client.get(f"/api/v1/continuity-plans/{plan_p}/membership")
    assert membership.status_code == 200, membership.text
    pairs = {
        (link["source_issue_id"], link["target_issue_id"])
        for link in membership.json()["dependencies"]
    }
    assert pairs == {(prereq_b.id, target_d.id), (prereq_c.id, target_d.id)}

    edges = await reading_plan_repository.list_plan_dependency_edges(
        async_db, plan_id=plan_p
    )
    assert {(edge.source_issue_id, edge.target_issue_id) for edge in edges} == pairs


@pytest.mark.asyncio
async def test_issue_read_state_is_global_across_overlapping_plans(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Reading a shared Issue advances progress in every overlapping plan."""
    user = await get_or_create_user_async(async_db)
    shared = await _make_issue(async_db, user_id=user.id, suffix="shared")
    other = await _make_issue(async_db, user_id=user.id, suffix="other")
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client,
        "Plan P",
        [_node("p-shared", shared.id, 0), _node("p-other", other.id, 1)],
    )
    plan_q = await _create_plan(
        auth_client, "Plan Q", [_node("q-shared", shared.id, 0)]
    )

    marked = await auth_client.post(f"/api/v1/issues/{shared.id}:markRead")
    assert marked.status_code == 204, marked.text

    membership_p = await auth_client.get(f"/api/v1/continuity-plans/{plan_p}/membership")
    membership_q = await auth_client.get(f"/api/v1/continuity-plans/{plan_q}/membership")
    assert membership_p.json()["progress"] == {"total_issues": 2, "read_issues": 1}
    assert membership_q.json()["progress"] == {"total_issues": 1, "read_issues": 1}


@pytest.mark.asyncio
async def test_provenance_round_trips_through_normalized_representation(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Source paths, positions, and advisory metadata survive normalization."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="sourced")
    await async_db.commit()

    nodes = [
        _node(
            "first",
            issue.id,
            0,
            extra={
                "label": "Starman #55",
                "source_role": "core",
                "source_confidence": "high",
                "source_explanation": "Template spine",
                "source_paths": ["DC/Starman.cbl"],
                "source_cbl_placements": [
                    {"source_path": "DC/Starman.cbl", "position": 55},
                    {"source_path": "DC/Events.cbl", "position": 7},
                ],
                "reader_role": "required/core",
                "reader_optional": False,
                "is_checkpoint": True,
            },
        ),
        _node("recap", issue.id, 1, extra={"label": "Recap context"}),
    ]
    plan_id = await _create_plan(auth_client, "Sourced plan", nodes)

    membership = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/membership")
    assert membership.status_code == 200, membership.text
    body = membership.json()

    # Repeated occurrences keep display context; distinct membership is one Issue.
    assert [(row["occurrence_id"], row["issue_id"]) for row in body["issues"]] == [
        ("first", issue.id),
        ("recap", issue.id),
    ]
    assert body["progress"] == {"total_issues": 1, "read_issues": 0}
    first = next(row for row in body["issues"] if row["occurrence_id"] == "first")
    assert first["source_metadata"] == {
        "source_role": "core",
        "source_confidence": "high",
        "source_explanation": "Template spine",
    }
    assert first["is_checkpoint"] is True
    assert first["reader_optional"] is False

    assert {source["raw_source_path"] for source in body["sources"]} == {
        "DC/Starman.cbl",
        "DC/Events.cbl",
    }
    by_path = {source["raw_source_path"]: source["id"] for source in body["sources"]}
    observed = {
        (placement["occurrence_id"], placement["plan_source_id"], placement["source_position"])
        for placement in body["placements"]
    }
    assert observed == {
        ("first", by_path["DC/Starman.cbl"], None),
        ("first", by_path["DC/Starman.cbl"], 55),
        ("first", by_path["DC/Events.cbl"], 7),
    }


@pytest.mark.asyncio
async def test_unlinking_one_plan_keeps_other_plan_reference(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unlink removes only the requesting plan's provenance link."""
    user = await get_or_create_user_async(async_db)
    source = await _make_issue(async_db, user_id=user.id, suffix="unlink-source")
    target = await _make_issue(async_db, user_id=user.id, suffix="unlink-target")
    await async_db.commit()
    dependency = await _make_dependency(
        async_db, source_id=source.id, target_id=target.id
    )
    await async_db.commit()

    plan_p = await _create_plan(
        auth_client, "Plan P", [_node("p-target", target.id, 0)]
    )
    plan_q = await _create_plan(
        auth_client, "Plan Q", [_node("q-target", target.id, 0)]
    )
    for plan_id in (plan_p, plan_q):
        linked = await auth_client.post(
            f"/api/v1/continuity-plans/{plan_id}/dependencies/{dependency.id}", json={}
        )
        assert linked.status_code == 201, linked.text

    unlinked = await auth_client.delete(
        f"/api/v1/continuity-plans/{plan_p}/dependencies/{dependency.id}"
    )
    assert unlinked.status_code == 204, unlinked.text

    membership_q = await auth_client.get(f"/api/v1/continuity-plans/{plan_q}/membership")
    assert [link["dependency_id"] for link in membership_q.json()["dependencies"]] == [
        dependency.id
    ]
    assert await async_db.get(Dependency, dependency.id) is not None

    missing = await auth_client.delete(
        f"/api/v1/continuity-plans/{plan_p}/dependencies/{dependency.id}"
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_link_rejects_unknown_dependency_and_foreign_edge(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Linking validates edge existence and endpoint ownership."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="link-target")
    other_user = await get_or_create_user_async(async_db, username="plan-link-other")
    foreign_source = await _make_issue(async_db, user_id=other_user.id, suffix="foreign")
    await async_db.commit()
    foreign_edge = await _make_dependency(
        async_db, source_id=foreign_source.id, target_id=target.id
    )
    await async_db.commit()

    plan_id = await _create_plan(
        auth_client, "Plan", [_node("node", target.id, 0)]
    )
    unknown = await auth_client.post(
        f"/api/v1/continuity-plans/{plan_id}/dependencies/987654321", json={}
    )
    assert unknown.status_code == 404
    foreign = await auth_client.post(
        f"/api/v1/continuity-plans/{plan_id}/dependencies/{foreign_edge.id}", json={}
    )
    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == "dangling_plan_reference"


@pytest.mark.asyncio
async def test_membership_rebuild_keeps_distinct_progress_with_duplicates(
    async_db: AsyncSession,
) -> None:
    """Progress counts distinct Issues, not duplicate occurrences."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="duplicate")
    plan = ContinuityPlan(
        user_id=user.id,
        name="Duplicates",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()

    nodes = [
        ContinuityPlanNode(
            id="first",
            node_type="issue",
            ref_id=issue.id,
            lane_id="main",
            position=0,
        ),
        ContinuityPlanNode(
            id="recap",
            node_type="issue",
            ref_id=issue.id,
            lane_id="main",
            position=1,
        ),
    ]
    await reading_plan_normalization.rebuild_plan_membership(
        async_db, plan_id=plan.id, nodes=nodes
    )
    rows = await reading_plan_repository.list_plan_issues(async_db, plan_id=plan.id)
    assert len(rows) == 2
    assert isinstance(rows[0], ReadingPlanIssue)
    total, read = await reading_plan_normalization.get_plan_progress(
        async_db, plan_id=plan.id
    )
    assert (total, read) == (1, 0)
    links = await reading_plan_repository.list_plan_dependencies(async_db, plan_id=plan.id)
    assert all(isinstance(link, ReadingPlanDependency) for link in links)
