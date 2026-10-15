"""Behavioral coverage of direct Reading List authoring without dependency compilation."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.collection_exclusion import CollectionExclusion
from app.models.dependency import Dependency
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async
from tests.test_custom_cbl_api import _issue


async def _members(db: AsyncSession, count: int = 3) -> list[int]:
    """Create independently progressing series to expose list constraints."""
    user = await get_or_create_user_async(db)
    ids = []
    for index in range(count):
        issue = await _issue(
            db, user_id=user.id, title=f"Series {index}", issue_number="1", queue_position=index + 1
        )
        ids.append(issue.id)
    await db.commit()
    return ids


@pytest.mark.asyncio
async def test_gate_reorder_requires_exact_named_preview(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A preview rolls back, preserves historical targets, and accepts only the current diff."""
    a, b, c = await _members(async_db)
    body = {
        "name": "X-Men",
        "issue_ids": [a, b, c],
        "mode": "loose",
        "entry_intents": {str(c): {"gate": "after_previous"}},
        "checkpoint_targets": {str(a): [c]},
    }
    created = await auth_client.post("/api/v1/custom-cbls", json=body)
    assert created.status_code == 201, created.text
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    reorder = {"name": "X-Men", "issue_ids": [b, a, c]}
    preview = await auth_client.put(url, json=reorder)
    assert preview.status_code == 409, preview.text
    changes = preview.json()["detail"]["predecessor_changes"]
    assert changes == [
        {
            "issue_id": c,
            "issue_name": "Series 2 #1",
            "before_issue_ids": [b],
            "before_issue_names": ["Series 1 #1"],
            "after_issue_ids": [a],
            "after_issue_names": ["Series 0 #1"],
        }
    ]
    unchanged = (await auth_client.get(url)).json()
    assert [e["issue_id"] for e in unchanged["entries"]] == [a, b, c]
    stale = await auth_client.put(url, json={**reorder, "confirmed_predecessor_changes": []})
    assert stale.status_code == 409
    saved = await auth_client.put(url, json={**reorder, "confirmed_predecessor_changes": changes})
    assert saved.status_code == 200, saved.text
    assert saved.json()["predecessor_changes"] == changes
    assert saved.json()["entries"][1]["checkpoint_target_issue_ids"] == [c]
    assert list((await async_db.scalars(select(Dependency))).all()) == []


@pytest.mark.asyncio
async def test_global_three_list_cycle_rolls_back(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Cycle checks include overlapping lists and already-read Issues."""
    a, b, c = await _members(async_db)
    read = await async_db.get(Issue, a)
    assert read is not None
    read.status = "read"
    await async_db.commit()
    for name, ids in (("First", [a, b]), ("Second", [b, c])):
        response = await auth_client.post(
            "/api/v1/custom-cbls",
            json={
                "name": name,
                "issue_ids": ids,
                "mode": "strict",
            },
        )
        assert response.status_code == 201, response.text
    cycle = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Third",
            "issue_ids": [c, a],
            "mode": "strict",
        },
    )
    assert cycle.status_code == 422, cycle.text
    assert cycle.json()["detail"]["code"] == "reading_list_cycle"
    assert "First" in cycle.json()["detail"]["message"]
    assert len((await auth_client.get("/api/v1/custom-cbls")).json()) == 2


@pytest.mark.asyncio
async def test_gate_removal_preserves_stable_prerequisite_and_read_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """List edits and deletion cannot rewrite stable source/target requirements."""
    a, b, c = await _members(async_db)
    requirement = Dependency(source_issue_id=a, target_issue_id=c, note="reader-authored")
    async_db.add(requirement)
    await async_db.commit()
    requirement_id = requirement.id
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Starman/JSA",
            "issue_ids": [a, b, c],
            "mode": "loose",
            "entry_intents": {str(c): {"gate": "hold"}},
        },
    )
    assert created.status_code == 201, created.text
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    saved = await auth_client.put(
        url,
        json={
            "name": "Starman/JSA",
            "issue_ids": [a, b, c],
            "entry_intents": {str(c): {"gate": "none"}, str(b): {"skipped": True}},
        },
    )
    # A skip edit changes positional requirements, so acknowledge the concrete preview.
    if saved.status_code == 409:
        saved = await auth_client.put(
            url,
            json={
                "name": "Starman/JSA",
                "issue_ids": [a, b, c],
                "entry_intents": {str(c): {"gate": "none"}, str(b): {"skipped": True}},
                "confirmed_predecessor_changes": saved.json()["detail"]["predecessor_changes"],
            },
        )
    assert saved.status_code == 200, saved.text
    assert saved.json()["entries"][2]["gate"] == "none"
    assert saved.json()["entries"][1]["skipped"] is True
    legacy = await auth_client.put(url, json={"name": "Starman/JSA", "issue_ids": [a, b, c]})
    assert legacy.status_code == 200
    assert legacy.json()["entries"][1]["skipped"] is True
    assert all(e["status"] == "unread" for e in legacy.json()["entries"])
    assert (await auth_client.delete(url)).status_code == 204
    async_db.expire_all()
    persisted = await async_db.get(Dependency, requirement_id)
    assert persisted is not None
    assert (persisted.source_issue_id, persisted.target_issue_id, persisted.note) == (
        a,
        c,
        "reader-authored",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target", ["issue", "thread", "volume", "canonical_volume", "issue_volume"]
)
async def test_exclusion_stranding_requirement_fails_closed(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    target: str,
) -> None:
    """Authoring cannot silently hide an excluded prerequisite source."""
    a, b, _ = await _members(async_db)
    user = await get_or_create_user_async(async_db)
    async_db.add(Dependency(source_issue_id=a, target_issue_id=b))
    issue = await async_db.get(Issue, a)
    assert issue is not None
    if target == "issue":
        exclusion = CollectionExclusion(user_id=user.id, issue_id=a)
    elif target == "thread":
        exclusion = CollectionExclusion(user_id=user.id, thread_id=issue.thread_id)
    else:
        identity = ExternalIdentity(provider="comicvine", entity_type="series", external_id="42")
        async_db.add(identity)
        await async_db.flush()
        if target == "volume":
            async_db.add(
                ThreadExternalSeriesMapping(
                    thread_id=issue.thread_id,
                    external_identity_id=identity.id,
                    status="confirmed",
                )
            )
        else:
            catalog = CatalogSeries(canonical_external_identity_id=identity.id)
            async_db.add(catalog)
            await async_db.flush()
            if target == "issue_volume":
                issue_identity = ExternalIdentity(
                    provider="comicvine",
                    entity_type="issue",
                    external_id="123",
                )
                async_db.add(issue_identity)
                await async_db.flush()
                catalog_issue = CatalogIssue(
                    canonical_external_identity_id=issue_identity.id,
                    catalog_series_id=catalog.id,
                )
                async_db.add(catalog_issue)
                await async_db.flush()
                issue.catalog_issue_id = catalog_issue.id
            else:
                thread = await async_db.get(Thread, issue.thread_id)
                assert thread is not None
                thread.catalog_series_id = catalog.id
        exclusion = CollectionExclusion(
            user_id=user.id,
            provider="comicvine",
            external_volume_id="42",
        )
    async_db.add(exclusion)
    await async_db.commit()
    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Invalid",
            "issue_ids": [a, b],
        },
    )
    assert response.status_code == 422, response.text
    assert "strands" in response.json()["detail"]["message"]
    assert (await auth_client.get("/api/v1/custom-cbls")).json() == []


@pytest.mark.asyncio
async def test_invalid_intent_membership_is_rejected(auth_client: AsyncClient) -> None:
    """Intent cannot be attached to a nonmember Issue."""
    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Invalid",
            "issue_ids": [],
            "entry_intents": {"999": {"gate": "hold"}},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_strict_reorder_and_skip_confirm_full_effective_changes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Strict lists report all changed requirements, including local skip effects."""
    a, b, c = await _members(async_db)
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Julix",
            "issue_ids": [a, b, c],
            "mode": "strict",
        },
    )
    assert created.status_code == 201, created.text
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    body = {"name": "Julix", "issue_ids": [c, b, a], "entry_intents": {str(b): {"skipped": True}}}
    preview = await auth_client.put(url, json=body)
    assert preview.status_code == 409, preview.text
    changes = preview.json()["detail"]["predecessor_changes"]
    by_issue = {change["issue_id"]: change for change in changes}
    assert by_issue[a]["after_issue_ids"] == [c]
    assert by_issue[b]["after_issue_ids"] == []
    assert by_issue[c]["before_issue_ids"] == [a, b]
    saved = await auth_client.put(url, json={**body, "confirmed_predecessor_changes": changes})
    assert saved.status_code == 200, saved.text
    assert saved.json()["mode"] == "strict"
    assert [e["issue_id"] for e in saved.json()["entries"]] == [c, b, a]
    assert saved.json()["entries"][1]["skipped"] is True


@pytest.mark.asyncio
async def test_series_and_stable_prerequisite_cycles_reject_atomically(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A failed mode edit restores metadata and cannot reverse a stable requirement."""
    a, b, c = await _members(async_db)
    async_db.add(Dependency(source_issue_id=a, target_issue_id=c, note="explicit"))
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Original",
            "issue_ids": [c, b, a],
        },
    )
    assert created.status_code == 201, created.text
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    rejected = await auth_client.put(
        url,
        json={
            "name": "Must roll back",
            "issue_ids": [c, b, a],
            "mode": "strict",
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "prerequisite" in rejected.json()["detail"]["message"]
    current = (await auth_client.get(url)).json()
    assert current["name"] == "Original" and current["mode"] == "loose"


@pytest.mark.asyncio
async def test_series_order_cannot_be_reversed_by_a_list(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A list cannot override natural series order, even with a confirmed preview."""
    a, b, _ = await _members(async_db)
    first = await async_db.get(Issue, a)
    second = await async_db.get(Issue, b)
    assert first is not None and second is not None
    second.thread_id = first.thread_id
    second.issue_number = "2"
    second.position = 2
    await async_db.commit()
    rejected = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Reversed series",
            "issue_ids": [b, a],
            "mode": "strict",
            "confirmed_predecessor_changes": [],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "series order" in rejected.json()["detail"]["message"]
    assert (await auth_client.get("/api/v1/custom-cbls")).json() == []
