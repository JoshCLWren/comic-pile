"""API coverage for external crossover template preview and adoption."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession, *, user_id: int, suffix: str, position: int = 1
) -> Issue:
    """Create one owned issue for template adoption tests."""
    thread = Thread(
        title=f"Template {suffix}",
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
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=position,
        status="unread",
    )
    async_db.add(issue)
    await async_db.flush()
    return issue


async def _seed_template_evidence(
    async_db: AsyncSession,
    *,
    issues: list[Issue],
) -> int:
    """Persist CBL + comicvine evidence linking the given issues to one list.

    Returns the CBL source list id whose derived template will contain all
    provided issues in their given order.
    """
    source = CBLSource(
        repository="repo/events",
        revision_sha="sha-1",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Events/Crossover.cbl",
        name="Crossover",
        declared_issue_count=len(issues),
        content_hash="hash-1",
        revision_sha="sha-1",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    for position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-{issue.id}",
            metadata_json={"story_arcs": [{"id": "123"}]},
        )
        async_db.add(identity)
        await async_db.flush()
        mapping = IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
        async_db.add(mapping)
        await async_db.flush()
        await _seed_template_entry(
            async_db,
            source_list=source_list,
            position=position,
            series_name="Crossover",
            issue_number="1",
            external_issue_identity_id=identity.id,
        )
    return source_list.id


async def _seed_template_entry(
    async_db: AsyncSession,
    *,
    source_list: CBLSourceList,
    position: int,
    series_name: str,
    issue_number: str,
    external_issue_identity_id: int,
) -> None:
    """Persist one CBL entry linked to the given external issue identity."""
    entry = CBLSourceEntry(
        list_id=source_list.id,
        position=position,
        series_name=series_name,
        issue_number=issue_number,
        external_issue_identity_id=external_issue_identity_id,
    )
    async_db.add(entry)
    await async_db.flush()


async def _seed_unmatched_entry(
    async_db: AsyncSession,
    *,
    source_list: CBLSourceList,
    position: int,
    series_name: str = "Unmatched",
) -> None:
    """Persist a CBL entry with no confirmed ComicPile mapping.

    The entry carries an embedded ComicVine identity that has no confirmed
    issue mapping, so it must be surfaced as an unresolved match rather than
    being silently dropped from the template.
    """
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"4100-{position}",
        metadata_json={},
    )
    async_db.add(identity)
    await async_db.flush()
    await _seed_template_entry(
        async_db,
        source_list=source_list,
        position=position,
        series_name=series_name,
        issue_number=str(position),
        external_issue_identity_id=identity.id,
    )


@pytest.mark.asyncio
async def test_preview_is_non_mutating(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Previewing a derived template must not create plans or rules."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=issues)
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/preview",
        json={"source_list_ids": [list_id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["issue_id"] for item in body["items"]] == [issue.id for issue in issues]

    plan_count = await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan)
    )
    rule_count = await async_db.scalar(
        select(func.count()).select_from(ContinuityRule)
    )
    assert plan_count == 0, "preview must not persist a plan"
    assert rule_count == 0, "preview must not compile continuity rules"


@pytest.mark.asyncio
async def test_adopt_linear_list_creates_zero_hard_rules(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A long imported order stays informational: no auto-generated edges.

    This is the core semantic guardrail from issue #1023: importing a linear
    external list must never implicitly become N-1 hard dependencies.
    """
    user = await get_or_create_user_async(async_db)
    issues = [
        await _make_issue(async_db, user_id=user.id, suffix=str(i), position=i)
        for i in range(12)
    ]
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=issues)
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/adopt",
        json={
            "source_list_ids": [list_id],
            "plan_name": "Imported Crossover",
            "ordering_mode": "informational",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ordering_mode"] == "informational"
    assert [node["ref_id"] for node in body["nodes"]] == [issue.id for issue in issues]

    rules = list(
        (
            await async_db.execute(
                select(ContinuityRule).where(ContinuityRule.user_id == user.id)
            )
        ).scalars().all()
    )
    assert rules == [], "informational adoption must not create continuity rules"


@pytest.mark.asyncio
async def test_adopt_strict_sequential_compiles_explicit_rules(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Only explicit blocking semantics compile hard rules."""
    user = await get_or_create_user_async(async_db)
    issues = [
        await _make_issue(async_db, user_id=user.id, suffix=str(i), position=i)
        for i in range(3)
    ]
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=issues)
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/adopt",
        json={
            "source_list_ids": [list_id],
            "plan_name": "Blocking Crossover",
            "ordering_mode": "strict_sequential",
        },
    )
    assert response.status_code == 201, response.text

    rules = list(
        (
            await async_db.execute(
                select(ContinuityRule).where(ContinuityRule.user_id == user.id)
            )
        ).scalars().all()
    )
    assert len(rules) == 2, "strict adoption of a 3-issue list compiles two edges"


@pytest.mark.asyncio
async def test_adopt_rejects_unowned_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Adoption must refuse template items the caller does not own."""
    user = await get_or_create_user_async(async_db)
    foreign_user = User(
        username="foreign-template-user",
        created_at=datetime.now(UTC),
    )
    async_db.add(foreign_user)
    await async_db.flush()
    owned = await _make_issue(async_db, user_id=user.id, suffix="owned")
    foreign = await _make_issue(async_db, user_id=foreign_user.id, suffix="foreign")
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=[owned, foreign])
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/adopt",
        json={
            "source_list_ids": [list_id],
            "plan_name": "Mixed Crossover",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "template_item_not_owned"

    plan_count = await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan)
    )
    assert plan_count == 0, "no plan is created when adoption is rejected"


@pytest.mark.asyncio
async def test_preview_surfaces_unresolved_matches(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Preview must show unmatched CBL entries instead of silently dropping them."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=issues)
    list_obj = await async_db.get(CBLSourceList, list_id)
    assert list_obj is not None
    await _seed_unmatched_entry(
        async_db,
        source_list=list_obj,
        position=3,
        series_name="Unmatched Spoiler",
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/preview",
        json={"source_list_ids": [list_id]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["issue_id"] for item in body["items"]] == [issue.id for issue in issues]
    assert len(body["unresolved"]) == 1
    match = body["unresolved"][0]
    assert match["series_name"] == "Unmatched Spoiler"
    assert match["issue_number"] == "3"
    assert match["position"] == 3
    assert match["reason"] == "no confirmed ComicPile mapping"
    assert match["source_path"] == "repo/events:Events/Crossover.cbl"


@pytest.mark.asyncio
async def test_preview_target_story_arc_marks_core_members(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Passing target_story_arc_id marks matching members as core over HTTP."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    list_id = await _seed_template_evidence(async_db, issues=issues)
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/crossover-templates/preview",
        json={"source_list_ids": [list_id], "target_story_arc_id": "123"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == len(issues)
    assert all(item["role"] == "core" for item in body["items"])
    assert all(item["target_story_arc_id"] == "123" for item in body["items"])


@pytest.mark.asyncio
async def test_preview_rejects_boolean_source_list_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Preview must reject bool source_list_ids, not coerce True to list id 1."""
    await get_or_create_user_async(async_db)

    response = await auth_client.post(
        "/api/v1/crossover-templates/preview",
        json={"source_list_ids": [True]},
    )
    assert response.status_code == 422, response.text
    assert "positive integers" in response.text


@pytest.mark.asyncio
async def test_adopt_rejects_boolean_source_list_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Adoption must reject bool source_list_ids, not coerce True to list id 1."""
    await get_or_create_user_async(async_db)

    response = await auth_client.post(
        "/api/v1/crossover-templates/adopt",
        json={
            "source_list_ids": [True],
            "plan_name": "Bool Crossover",
        },
    )
    assert response.status_code == 422, response.text
    assert "positive integers" in response.text
