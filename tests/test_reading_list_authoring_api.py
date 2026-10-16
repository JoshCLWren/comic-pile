"""Behavioral coverage of direct Reading List authoring without dependency compilation."""

from unittest.mock import AsyncMock, patch

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
    path = cycle.json()["detail"]["path"]
    assert path
    canonical = {a: "Series 0 #1", b: "Series 1 #1", c: "Series 2 #1"}
    for edge in path:
        assert edge["source_issue_name"] == canonical[edge["source_issue_id"]]
        assert edge["target_issue_name"] == canonical[edge["target_issue_id"]]
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
    assert saved.status_code == 409, saved.text
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
    assert "historical classification unknown" in rejected.json()["detail"]["message"]
    requirement_edge = next(
        edge
        for edge in rejected.json()["detail"]["path"]
        if edge["prerequisite_origin"] is not None
    )
    assert requirement_edge["prerequisite_origin"] == "converted"
    assert requirement_edge["provenance"] == ["historical classification unknown", "explicit"]
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
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert "series order" in rejected.json()["detail"]["message"]
    assert (await auth_client.get("/api/v1/custom-cbls")).json() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", [{"mode": "strict"}, {"gate": "hold"}, {"gate": "after_previous"}])
async def test_mode_and_gate_only_edits_require_confirmation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    edit: dict[str, str],
) -> None:
    """New positional requirements always require confirmation on existing lists."""
    a, b, c = await _members(async_db)
    created = await auth_client.post(
        "/api/v1/custom-cbls", json={"name": "Order", "issue_ids": [a, b, c]}
    )
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    body = {
        "name": "Order",
        "issue_ids": [a, b, c],
        **({"mode": edit["mode"]} if "mode" in edit else {"entry_intents": {str(b): edit}}),
    }
    preview = await auth_client.put(url, json=body)
    assert preview.status_code == 409, preview.text
    changes = preview.json()["detail"]["predecessor_changes"]
    assert changes
    saved = await auth_client.put(url, json={**body, "confirmed_predecessor_changes": changes})
    assert saved.status_code == 200, saved.text


@pytest.mark.asyncio
async def test_confirmation_uses_identity_and_loads_library_once(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Names and display ordering do not invalidate unchanged semantic consent."""
    from app.repositories import reading_list_authoring_repository as repository

    a, b, c = await _members(async_db)
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Order",
            "issue_ids": [a, b, c],
            "mode": "strict",
        },
    )
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    body = {"name": "Order", "issue_ids": [c, b, a]}
    preview = await auth_client.put(url, json=body)
    assert preview.status_code == 409, preview.text
    changes = list(reversed(preview.json()["detail"]["predecessor_changes"]))
    for change in changes:
        change["issue_name"] = "old display name"
        change["before_issue_names"] = []
        change["after_issue_names"] = []
    issue = await async_db.get(Issue, a)
    assert issue is not None
    thread = await async_db.get(Thread, issue.thread_id)
    assert thread is not None
    thread.title = "Renamed"
    await async_db.commit()
    with patch.object(repository, "load_issues", AsyncMock(wraps=repository.load_issues)) as load:
        saved = await auth_client.put(url, json={**body, "confirmed_predecessor_changes": changes})
        assert saved.status_code == 200, saved.text
        load.assert_awaited_once()


@pytest.mark.asyncio
async def test_excluded_placements_still_preview_stored_constraint_changes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Exclusion does not conceal the ordering constraints retained by validation."""
    a, b, c = await _members(async_db)
    user = await get_or_create_user_async(async_db)
    async_db.add_all([CollectionExclusion(user_id=user.id, issue_id=i) for i in (a, b, c)])
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Excluded",
            "issue_ids": [a, b, c],
            "mode": "strict",
        },
    )
    assert created.status_code == 201, created.text
    url = f"/api/v1/custom-cbls/{created.json()['id']}"
    preview = await auth_client.put(url, json={"name": "Excluded", "issue_ids": [c, b, a]})
    assert preview.status_code == 409, preview.text
    assert len(preview.json()["detail"]["predecessor_changes"]) == 3


@pytest.mark.asyncio
async def test_strict_authoring_warns_about_omitted_unread_series_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Partial Thread coverage warns without inventing constraints for omitted Issues."""
    a, b, _ = await _members(async_db)
    first = await async_db.get(Issue, a)
    second = await async_db.get(Issue, b)
    assert first is not None and second is not None
    second.thread_id = first.thread_id
    second.issue_number = "2"
    second.position = 2
    await async_db.commit()
    created = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Partial",
            "issue_ids": [a],
            "mode": "strict",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["warnings"] == [
        "Strict list omits 1 unread Issues from Series 0: Series 0 #2"
    ]


@pytest.mark.asyncio
async def test_confirmation_is_put_only(auth_client: AsyncClient) -> None:
    """Creation rejects an acknowledgement that has no previous list to describe."""
    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "New",
            "issue_ids": [],
            "confirmed_predecessor_changes": [],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "reading_list_confirmation_put_only"


@pytest.mark.asyncio
async def test_warning_bounds_samples_and_counts_skipped_placements(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Large Threads produce a bounded sample, counting deliberately skipped members."""
    a, _, _ = await _members(async_db)
    first = await async_db.get(Issue, a)
    assert first is not None
    for position in range(2, 62):
        async_db.add(
            Issue(thread_id=first.thread_id, issue_number=str(position), position=position)
        )
    await async_db.commit()
    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Partial",
            "mode": "strict",
            "issue_ids": [a],
            "entry_intents": {str(a): {"skipped": True}},
        },
    )
    assert response.status_code == 201, response.text
    warning = response.json()["warnings"][0]
    assert "omits 61 unread Issues" in warning
    assert "Series 0 #1" in warning  # The skipped placement is omitted from execution.
    assert "#6" not in warning and "(+56 more)" in warning
    assert len(warning) < 600
    opened = await auth_client.get(f"/api/v1/custom-cbls/{response.json()['id']}")
    assert opened.json()["warnings"] == []  # Explicitly write-time diagnostics.


@pytest.mark.asyncio
async def test_warning_bounds_affected_threads_and_display_lengths(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Many partial Threads cannot expand a response into a full library inventory."""
    ids = await _members(async_db, count=12)
    for index, issue_id in enumerate(ids):
        first = await async_db.get(Issue, issue_id)
        assert first is not None
        thread = await async_db.get(Thread, first.thread_id)
        assert thread is not None
        thread.title = f"{index:02d}" + "x" * 198
        async_db.add(Issue(thread_id=first.thread_id, issue_number="2", position=2))
    await async_db.commit()
    response = await auth_client.post(
        "/api/v1/custom-cbls",
        json={
            "name": "Partial",
            "mode": "strict",
            "issue_ids": ids,
        },
    )
    assert response.status_code == 201, response.text
    warnings = response.json()["warnings"]
    assert len(warnings) == 11
    assert warnings[-1] == "Partial coverage also affects 2 more Threads."
    assert all(len(warning) < 250 for warning in warnings)


@pytest.mark.asyncio
async def test_snapshot_corruption_is_not_misreported_as_reader_input(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Impossible missing-reference snapshots remain internal invariant errors."""
    from app.repositories import reading_list_authoring_repository as repository
    from app.services.reading_list_authoring import load_authoring_snapshot

    a, _, _ = await _members(async_db)
    user = await get_or_create_user_async(async_db)
    created = await auth_client.post(
        "/api/v1/custom-cbls", json={"name": "Order", "issue_ids": [a]}
    )
    assert created.status_code == 201, created.text
    with patch.object(repository, "load_issues", AsyncMock(return_value=[])):
        with pytest.raises(ValueError, match="missing referenced issues"):
            await load_authoring_snapshot(async_db, user.id)
