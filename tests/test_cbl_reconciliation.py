"""Tests for CBL source reconciliation and the crossover rebuild repair path."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.cbl_reconciliation import (
    calculate_cbl_adoption_plan,
    cbl_comicvine_series_id,
    cbl_series_group_id,
    preview_cbl_adoption,
    reconcile_cbl_source_list,
)
from app.api.issue_identity import CBLAdoptionPreviewResponse
from scripts.rebuild_crossover_from_cbl import _member_issue_ids, _rebuild
from tests.conftest import get_or_create_user_async


async def _make_issue(
    async_db: AsyncSession,
    *,
    user_id: int,
    issue_number: str,
    position: int,
    status: str = "unread",
    read_at: datetime | None = None,
    thread_title: str = "Series",
) -> Issue:
    """Create one owned issue plus its owning thread."""
    thread = Thread(
        title=thread_title,
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
        issue_number=issue_number,
        position=position,
        status=status,
        read_at=read_at,
    )
    async_db.add(issue)
    await async_db.flush()
    return issue


async def _seed_source_list(
    async_db: AsyncSession,
    *,
    issues: list[Issue],
    issues_by_position: dict[int, str] | None = None,
    series_names: dict[int, str] | None = None,
    source_path: str = "Ultimate.cbl",
    omit_identity_at: set[int] | None = None,
) -> int:
    """Persist one CBL source list whose entries map to given issues in order."""
    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="sha-1",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=source_path,
        name="Ultimate Universe",
        declared_issue_count=len(issues),
        content_hash="hash-1",
        revision_sha="sha-1",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    for index, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"4000-{issue.id}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        if index not in (omit_identity_at or set()):
            async_db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                )
            )
            await async_db.flush()
        async_db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=index,
                series_name=(series_names or {}).get(index, "Series"),
                issue_number=(issues_by_position or {}).get(index, issue.issue_number),
                external_issue_identity_id=identity.id,
            )
        )
        await async_db.flush()
    return source_list.id


async def _make_group(
    async_db: AsyncSession,
    *,
    user_id: int,
    name: str = "Ultimate Universe",
    issue_ids: tuple[int, ...] = (),
) -> DependencyGroup:
    """Create one dependency group with optional issue members."""
    group = DependencyGroup(user_id=user_id, name=name)
    async_db.add(group)
    await async_db.flush()
    for issue_id in issue_ids:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue_id))
    await async_db.flush()
    return group


@pytest.mark.asyncio
async def test_reconcile_preserves_full_source_order_including_read_entries(
    async_db: AsyncSession,
) -> None:
    """Read and unread source entries remain position-for-position ordered."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    issues = [
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="1",
            position=1,
            status="read",
            read_at=now,
        ),
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="2",
            position=1,
            status="read",
            read_at=now,
        ),
        await _make_issue(
            async_db,
            user_id=user.id,
            issue_number="3",
            position=1,
        ),
    ]
    source_list_id = await _seed_source_list(async_db, issues=issues)

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list_id,
        user_id=user.id,
    )

    assert report.total_positions == 3
    assert [entry["cbl_position"] for entry in report.entries] == [1, 2, 3]
    assert [entry["resolved_issue_id"] for entry in report.entries] == [
        issue.id for issue in issues
    ]
    assert [entry["read_status"] for entry in report.entries] == [
        "read",
        "read",
        "unread",
    ]
    assert report.first_unread_position == 3
    assert report.first_unread_issue_id == issues[2].id
    assert report.first_unread_entry is not None
    assert report.first_unread_entry["resolved_issue_id"] == issues[2].id
    assert report.missing_source_entries == ()
    assert report.extra_member_issue_ids == ()
    assert report.ambiguous_mappings == ()
    assert report.source_list_id == source_list_id
    assert report.source_path == "Ultimate.cbl"


@pytest.mark.asyncio
async def test_reconcile_surfaces_unresolved_and_extra_members(
    async_db: AsyncSession,
) -> None:
    """Unresolved entries and baseline extras are never silently dropped."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    source_list_id = await _seed_source_list(
        async_db,
        issues=[issue],
        omit_identity_at={1},
    )

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list_id,
        user_id=user.id,
        baseline_member_issue_ids=(issue.id, 9999),
    )

    assert report.entries[0]["resolved_issue_id"] is None
    assert report.entries[0]["resolution_status"] in (
        "comicvine_identity_not_known",
        "ambiguous_no_comicvine_id",
        "no_owned_issue_for_comicvine_id",
        "unresolved",
    )
    assert report.unresolved_count == 1
    assert report.extra_member_issue_ids == (issue.id, 9999)


@pytest.mark.asyncio
async def test_reconcile_detects_duplicate_canonical_identity(
    async_db: AsyncSession,
) -> None:
    """Two owner issues on one ComicVine identity are reported as duplicate."""
    user = await get_or_create_user_async(async_db)
    first = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    second = await _make_issue(async_db, user_id=user.id, issue_number="2", position=1)

    source = CBLSource(
        repository="repo/events",
        revision_sha="sha-1",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Dup.cbl",
        name="Dup",
        declared_issue_count=1,
        content_hash="hash-1",
        revision_sha="sha-1",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-same",
        metadata_json={},
    )
    async_db.add(identity)
    await async_db.flush()
    for issue in (first, second):
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
            )
        )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Series",
            issue_number="1",
            external_issue_identity_id=identity.id,
        )
    )
    await async_db.flush()

    report = await reconcile_cbl_source_list(
        async_db,
        source_list_id=source_list.id,
        user_id=user.id,
    )

    assert report.entries[0]["is_duplicate_identity"] is True
    assert report.duplicate_identity_groups >= 1
    assert report.entries[0]["resolved_issue_id"] is not None


@pytest.mark.asyncio
async def test_reconcile_rejects_missing_source_list(
    async_db: AsyncSession,
) -> None:
    """A missing source list is rejected instead of reconciled as empty."""
    user = await get_or_create_user_async(async_db)
    for kwargs in ({"source_list_id": 999999}, {"list_id": 999999}):
        with pytest.raises(ValueError):
            await reconcile_cbl_source_list(
                async_db,
                user_id=user.id,
                **kwargs,
            )


@pytest.mark.asyncio
async def test_cbl_adoption_preview_is_read_only_and_supports_overrides(
    async_db: AsyncSession,
) -> None:
    """Planning preserves positions, read history, and all database counts."""
    user = await get_or_create_user_async(async_db)
    read_at = datetime.now(UTC)
    existing = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=read_at,
    )
    missing = await _make_issue(async_db, user_id=user.id, issue_number="2", position=1)
    source_list_id = await _seed_source_list(
        async_db,
        issues=[existing, missing],
        omit_identity_at={2},
        series_names={1: "Shared Run", 2: "Shared Run"},
    )
    source_entry = await async_db.scalar(
        select(CBLSourceEntry).where(
            CBLSourceEntry.list_id == source_list_id,
            CBLSourceEntry.position == 2,
        )
    )
    assert source_entry is not None
    async_db.add(
        CBLSourceEntry(
            list_id=source_list_id,
            position=3,
            series_name="Shared Run",
            issue_number="3",
        )
    )
    await async_db.flush()

    before = {
        table: await async_db.scalar(select(func.count()).select_from(model))
        for table, model in (
            ("issues", Issue),
            ("threads", Thread),
            ("memberships", DependencyGroupMembership),
        )
    }
    before_dependencies = await async_db.scalar(select(func.count()).select_from(Dependency))

    report, plan = await preview_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
    )
    assert plan.entries[0]["adoption_decision"] == "included_existing"
    assert plan.entries[1]["adoption_decision"] == "awaiting_opt_in"
    assert plan.entries[2]["adoption_decision"] == "unresolved"
    assert plan.final_adopted_order == (1,)
    assert plan.excluded_count == 0
    assert report.content_hash == "hash-1"
    assert report.revision_sha == "sha-1"
    repeat_report, _ = await preview_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
    )
    assert (
        report.source_list_id,
        report.source_path,
        report.content_hash,
        report.revision_sha,
    ) == (
        repeat_report.source_list_id,
        repeat_report.source_path,
        repeat_report.content_hash,
        repeat_report.revision_sha,
    )

    _, explicitly_included = await preview_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        entry_decisions={str(source_entry.id): True},
    )
    assert explicitly_included.entries[1]["adoption_decision"] == "would_create_missing"
    assert explicitly_included.entries[1]["adopted"] is True
    assert explicitly_included.final_adopted_order == (1, 2)
    assert explicitly_included.missing_would_create_count == 1

    # The grouping key is deterministic but opaque; use the returned key for
    # the same selection calculation to prove the per-entry override wins.
    series_key = str(plan.entries[0]["series_group_id"])
    _, overridden = await preview_cbl_adoption(
        async_db,
        user_id=user.id,
        list_id=source_list_id,
        series_decisions={series_key: False},
        entry_decisions={str(source_entry.id): True},
    )
    assert report.entries[0]["resolved_issue_id"] == existing.id
    assert report.entries[0]["read_status"] == "read"
    assert [entry["cbl_position"] for entry in overridden.entries] == [1, 2, 3]
    assert overridden.entries[0]["adoption_decision"] == "excluded"
    assert overridden.entries[0]["adoption_class"] == "existing"
    assert overridden.entries[1]["adoption_decision"] == "would_create_missing"
    assert overridden.entries[1]["adoption_class"] == "missing_importable"
    assert overridden.entries[2]["adoption_decision"] == "unresolved"
    assert overridden.entries[2]["adoption_class"] == "ambiguous_unresolved"
    assert overridden.final_adopted_order == (2,)
    assert overridden.reused_existing_count == 0
    assert overridden.missing_would_create_count == 1
    assert overridden.excluded_count == 1
    assert overridden.unresolved_count == 1
    assert before["issues"] == await async_db.scalar(select(func.count()).select_from(Issue))
    assert before["threads"] == await async_db.scalar(select(func.count()).select_from(Thread))
    assert before["memberships"] == await async_db.scalar(
        select(func.count()).select_from(DependencyGroupMembership)
    )
    assert before_dependencies == await async_db.scalar(
        select(func.count()).select_from(Dependency)
    )
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(Dependency)
            .where(Dependency.note.like("cbl-order:source:%"))
        )
        == 0
    )


def test_cbl_adoption_api_model_keeps_non_comicvine_series_provider_generic() -> None:
    """A non-ComicVine series identity is never exposed as a ComicVine ID."""
    entry = CBLAdoptionPreviewResponse.model_validate(
        {
            "source": {
                "source_list_id": 1,
                "source_repository": "repo",
                "source_path": "list.cbl",
                "content_hash": "hash",
                "revision_sha": "sha",
            },
            "total_positions": 1,
            "entries": [
                {
                    "cbl_position": 1,
                    "cbl_entry_id": 10,
                    "series_name": "Run",
                    "issue_number": "1",
                    "series_group_id": "provider-series:metron:42",
                    "adoption_class": "existing",
                    "adoption_decision": "included_existing",
                    "adopted": True,
                    "comicvine_issue_id": None,
                    "comicvine_series_id": None,
                    "series_provider": "MeTrOn",
                    "series_external_id": "42",
                    "resolved_issue_id": 7,
                    "canonical_issue_id": 7,
                    "read_status": "unread",
                    "read_at": None,
                    "resolution_status": "resolved_via_comicvine_canonical",
                    "is_duplicate_identity": False,
                }
            ],
            "summary": {
                "reused_existing_count": 1,
                "missing_would_create_count": 0,
                "excluded_count": 0,
                "unresolved_count": 0,
                "awaiting_opt_in_count": 0,
                "final_adopted_count": 1,
                "final_adopted_order": [1],
                "reused_existing_positions": [1],
                "missing_would_create_positions": [],
                "excluded_positions": [],
                "unresolved_positions": [],
                "awaiting_opt_in_positions": [],
            },
        }
    )
    assert entry.entries[0].series_provider == "MeTrOn"
    assert entry.entries[0].series_external_id == "42"
    assert entry.entries[0].comicvine_series_id is None


def test_cbl_comicvine_series_id_requires_comicvine_provider() -> None:
    """Provider-generic series IDs cannot be mislabeled as ComicVine IDs."""
    assert cbl_comicvine_series_id(
        {"series_provider": "MeTrOn", "series_external_id": "42"}
    ) is None
    assert cbl_comicvine_series_id(
        {"series_provider": "  COMICVINE ", "series_external_id": "42"}
    ) == "42"


def test_cbl_adoption_plan_does_not_auto_adopt_ambiguous_canonical_resolution() -> None:
    """Canonical/read-history evidence remains visible but requires reconciliation."""
    plan = calculate_cbl_adoption_plan(
        [
            {
                "cbl_position": 4,
                "cbl_entry_id": 40,
                "series_name": "Run",
                "issue_number": "4",
                "series_group_id": "run-key",
                "comicvine_issue_id": "4000-4",
                "resolved_issue_id": 99,
                "canonical_issue_id": 99,
                "read_status": "read",
                "read_at": "2026-01-01T00:00:00+00:00",
                "resolution_status": "resolved_via_comicvine_canonical_ambiguous",
            },
        ],
    )
    entry = plan.entries[0]
    assert entry["adoption_class"] == "ambiguous_unresolved"
    assert entry["adoption_decision"] == "unresolved"
    assert entry["adopted"] is False
    assert plan.final_adopted_order == ()
    assert entry["resolved_issue_id"] == 99
    assert entry["canonical_issue_id"] == 99
    assert entry["read_status"] == "read"


def test_cbl_adoption_plan_preserves_gapped_source_positions() -> None:
    """The pure planner keeps source positions as the adopted order."""
    plan = calculate_cbl_adoption_plan(
        [
            {
                "cbl_position": 2,
                "cbl_entry_id": 20,
                "series_name": "Run",
                "issue_number": "2",
                "series_group_id": "run-key",
                "resolution_status": "resolved_via_comicvine_canonical",
                "resolved_issue_id": 8,
            },
            {
                "cbl_position": 5,
                "cbl_entry_id": 50,
                "series_name": "Run",
                "issue_number": "5",
                "series_group_id": "run-key",
                "resolution_status": "no_owned_issue_for_comicvine_id",
                "resolved_issue_id": None,
            },
        ],
        series_decisions={"run-key": True},
    )
    assert plan.final_adopted_order == (2, 5)
    assert plan.final_adopted_count == 2


def test_cbl_series_group_id_does_not_confuse_identity_row_ids_with_external_ids() -> None:
    """Series grouping uses provider/external identity or a stable source fallback."""
    assert cbl_series_group_id(
        {"series_provider": "ComicVine", "series_external_id": "123", "series_name": "Run"}
    ) == "provider-series:comicvine:123"
    assert cbl_series_group_id(
        {
            "external_series_identity_id": 123,
            "series_name": "Run",
            "volume_year": 2024,
        }
    ).startswith("source-series:")


def test_cbl_adoption_selection_precedence_requires_missing_opt_in() -> None:
    """Series choices select missing entries, while entry choices take precedence."""
    entries = [
        {
            "cbl_position": 2,
            "cbl_entry_id": 20,
            "series_name": "Run",
            "issue_number": "2",
            "series_group_id": "run-key",
            "resolution_status": "resolved_via_comicvine_canonical",
            "resolved_issue_id": 8,
        },
        {
            "cbl_position": 5,
            "cbl_entry_id": 50,
            "series_name": "Run",
            "issue_number": "5",
            "series_group_id": "run-key",
            "resolution_status": "no_owned_issue_for_comicvine_id",
            "resolved_issue_id": None,
        },
    ]
    default = calculate_cbl_adoption_plan(entries)
    assert default.final_adopted_order == (2,)
    assert default.entries[1]["adoption_decision"] == "awaiting_opt_in"

    excluded = calculate_cbl_adoption_plan(entries, series_decisions={"run-key": False})
    assert excluded.final_adopted_order == ()
    assert [entry["adoption_decision"] for entry in excluded.entries] == [
        "excluded",
        "excluded",
    ]

    included = calculate_cbl_adoption_plan(
        entries,
        series_decisions={"run-key": True},
        entry_decisions={"20": False},
    )
    assert included.final_adopted_order == (5,)
    assert included.entries[0]["adoption_decision"] == "excluded"
    assert included.entries[1]["adoption_decision"] == "would_create_missing"


@pytest.mark.asyncio
async def test_cbl_adoption_endpoint_returns_typed_fingerprinted_contract(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The public preview endpoint exposes the client-ready typed contract."""
    user = await get_or_create_user_async(async_db)
    read_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    issue = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=read_at,
    )
    source_list_id = await _seed_source_list(async_db, issues=[issue])

    response = await auth_client.get(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-preview"
    )

    assert response.status_code == 200
    contract = CBLAdoptionPreviewResponse.model_validate(response.json())
    assert contract.source.source_list_id == source_list_id
    assert contract.source.content_hash == "hash-1"
    assert contract.source.revision_sha == "sha-1"
    assert contract.entries[0].adoption_decision == "included_existing"
    assert contract.entries[0].read_status == "read"
    assert response.json()["entries"][0]["read_at"] == "2026-01-02T03:04:05Z"
    assert contract.entries[0].read_at == read_at
    assert contract.summary.final_adopted_order == [1]

    openapi = (await auth_client.get("/openapi.json")).json()
    read_at_schema = openapi["components"]["schemas"]["CBLAdoptionEntryResponse"]["properties"][
        "read_at"
    ]
    assert read_at_schema["anyOf"] == [
        {"type": "string", "format": "date-time"},
        {"type": "null"},
    ]


@pytest.mark.asyncio
async def test_repair_rebuilds_membership_preserving_source_order(
    async_db: AsyncSession,
) -> None:
    """The rebuild restores every resolved entry with authoritative positions."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    read = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="1",
        position=1,
        status="read",
        read_at=now,
    )
    unread = await _make_issue(async_db, user_id=user.id, issue_number="2", position=1)
    not_in_source = await _make_issue(async_db, user_id=user.id, issue_number="3", position=1)
    source_list_id = await _seed_source_list(async_db, issues=[read, unread])
    group = await _make_group(
        async_db,
        user_id=user.id,
        issue_ids=(not_in_source.id, read.id),
    )

    args = argparse.Namespace(
        source_list_id=source_list_id,
        group_id=group.id,
        user_id=user.id,
        commit=True,
    )
    payload = await _rebuild(async_db, args)

    assert payload["entries_resolved"] == 2
    assert set(await _member_issue_ids(async_db, group.id)) == {
        read.id,
        unread.id,
    }
    assert payload["members_removed_extra"] == [not_in_source.id]
    assert payload["first_unread_issue_id"] == unread.id
    stored_unread = await async_db.get(Issue, unread.id)
    assert stored_unread is not None and stored_unread.status == "unread"

    rows = (
        (
            await async_db.execute(
                select(DependencyGroupMembership).where(
                    DependencyGroupMembership.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    order_map = {row.issue_id: row.sequence_order for row in rows}
    assert order_map[read.id] == 1
    assert order_map[unread.id] == 2


@pytest.mark.asyncio
async def test_repair_dry_run_does_not_mutate(
    async_db: AsyncSession,
) -> None:
    """Dry-run reports without changing crossover membership."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    source_list_id = await _seed_source_list(async_db, issues=[issue])
    group = await _make_group(async_db, user_id=user.id)

    args = argparse.Namespace(
        source_list_id=source_list_id,
        group_id=group.id,
        user_id=user.id,
        commit=False,
    )
    payload = await _rebuild(async_db, args)

    assert payload["dry_run"] is True
    assert payload["members_for_group_before"] == []
    assert await _member_issue_ids(async_db, group.id) == []
