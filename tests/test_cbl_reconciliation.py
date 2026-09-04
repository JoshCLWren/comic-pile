"""Tests for CBL source reconciliation and the crossover rebuild repair path."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import cast

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.cbl_reconciliation import (
    CBLAdoptionMaterializationError,
    CBLReviewedEntry,
    CBLReviewedSource,
    calculate_cbl_adoption_plan,
    cbl_comicvine_series_id,
    cbl_series_group_id,
    commit_cbl_adoption,
    preview_cbl_adoption,
    reconcile_cbl_source_list,
)
from app.services import cbl_reconciliation as cbl_service
from app.api.issue_identity import CBLAdoptionPreviewResponse
from scripts.rebuild_crossover_from_cbl import _member_issue_ids, _rebuild
from tests.conftest import get_or_create_user_async


def _thread_stub(thread_id: int) -> Thread:
    """Build an unpersisted thread with a stable ID for evidence tests."""
    thread = Thread(title="Run", format="Comic", issues_remaining=0, user_id=1)
    thread.id = thread_id
    return thread


def test_series_target_rejects_mapping_canonical_contradictions() -> None:
    """Confirmed mappings never override contradictory canonical issue evidence."""
    first = _thread_stub(10)
    second = _thread_stub(20)

    with pytest.raises(CBLAdoptionMaterializationError, match="contradicts"):
        cbl_service._target_from_series_evidence(
            provider="comicvine",
            external_id="series-1",
            mapped_threads=[first],
            canonical_thread_ids={second.id},
        )
    with pytest.raises(CBLAdoptionMaterializationError, match="contradicts"):
        cbl_service._target_from_series_evidence(
            provider="comicvine",
            external_id="series-1",
            mapped_threads=[first, second],
            canonical_thread_ids={30},
        )
    with pytest.raises(CBLAdoptionMaterializationError, match="multiple owned threads"):
        cbl_service._target_from_series_evidence(
            provider="comicvine",
            external_id="series-1",
            mapped_threads=[first, second],
            canonical_thread_ids={first.id, second.id},
        )


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
    series_ids: dict[int, str] | None = None,
    omit_series_identity_at: set[int] | None = None,
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
        series_identity = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id=(series_ids or {}).get(index, "series-1"),
            metadata_json={},
        )
        existing_series = await async_db.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == series_identity.provider,
                ExternalIdentity.entity_type == series_identity.entity_type,
                ExternalIdentity.external_id == series_identity.external_id,
            )
        )
        if existing_series is None:
            async_db.add(series_identity)
            await async_db.flush()
        else:
            series_identity = existing_series
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=str(issue.id),
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
                external_series_identity_id=(
                    None if index in (omit_series_identity_at or set()) else series_identity.id
                ),
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


def _commit_payload(
    preview: dict[str, object],
    *,
    series_decisions: dict[str, bool] | None = None,
    entry_decisions: dict[str, bool] | None = None,
) -> dict[str, object]:
    """Turn a reviewed preview response into the typed commit request."""
    summary = preview["summary"]
    assert isinstance(summary, dict)
    source = preview["source"]
    entries = preview["entries"]
    assert isinstance(source, dict)
    assert isinstance(entries, list)
    reviewed_entries: list[dict[str, object]] = []
    for entry in entries:
        assert isinstance(entry, dict)
        reviewed_entries.append(cast(dict[str, object], entry.copy()))
    return {
        "source": dict(source),
        "series_decisions": series_decisions or {},
        "entry_decisions": entry_decisions or {},
        "reviewed_entries": reviewed_entries,
        "reviewed_final_source_positions": list(summary["final_adopted_order"]),
    }


@pytest.mark.asyncio
async def test_commit_existing_only_preserves_history_and_gapped_source_order(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Existing adoption reuses physical issues and persists original positions."""
    user = await get_or_create_user_async(async_db)
    read_at = datetime(2026, 2, 3, tzinfo=UTC)
    first = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="2",
        position=1,
    )
    excluded_read_at = datetime(2026, 2, 2, tzinfo=UTC)
    excluded = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="5",
        position=1,
        status="read",
        read_at=excluded_read_at,
    )
    later = await _make_issue(
        async_db,
        user_id=user.id,
        issue_number="9",
        position=1,
        status="read",
        read_at=read_at,
    )
    source_list_id = await _seed_source_list(async_db, issues=[first, excluded, later])
    entries = list(
        (
            await async_db.scalars(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == source_list_id)
                .order_by(CBLSourceEntry.position)
            )
        ).all()
    )
    entries[2].position = 9
    await async_db.flush()
    entries[1].position = 5
    await async_db.flush()
    entries[0].position = 2
    await async_db.flush()
    before_issues = await async_db.scalar(select(func.count()).select_from(Issue))
    before_threads = await async_db.scalar(select(func.count()).select_from(Thread))

    decisions = {str(entries[1].id): False}
    preview_response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-plan",
        json={"series_decisions": {}, "entry_decisions": decisions},
    )
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit",
        json=_commit_payload(preview_response.json(), entry_decisions=decisions),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created_issue_ids"] == []
    assert body["created_thread_ids"] == []
    assert body["reused_issue_ids"] == [first.id, later.id]
    assert body["excluded_source_positions"] == [5]
    assert body["final_adopted_source_positions"] == [2, 9]
    assert [item["sequence_order"] for item in body["memberships"]] == [2, 9]
    assert before_issues == await async_db.scalar(select(func.count()).select_from(Issue))
    assert before_threads == await async_db.scalar(select(func.count()).select_from(Thread))
    preserved = await async_db.get(Issue, later.id)
    assert preserved is not None
    assert preserved.status == "read"
    assert preserved.read_at == read_at
    preserved_excluded = await async_db.get(Issue, excluded.id)
    assert preserved_excluded is not None
    assert preserved_excluded.status == "read"
    assert preserved_excluded.read_at == excluded_read_at
    assert excluded.id not in {item["issue_id"] for item in body["memberships"]}
    group = await async_db.get(DependencyGroup, body["group_id"])
    assert group is not None
    assert group.cbl_source_list_id == source_list_id
    assert group.cbl_content_hash == "hash-1"
    assert group.cbl_revision_sha == "sha-1"
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(Dependency)
            .where(Dependency.note.like("cbl-order:source:%"))
        )
        == 0
    )


@pytest.mark.asyncio
async def test_commit_imports_only_approved_missing_and_replays_idempotently(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Only opted-in missing comics use canonical import, and replay converges."""
    user = await get_or_create_user_async(async_db)
    missing = await _make_issue(async_db, user_id=user.id, issue_number="5", position=1)
    unapproved = await _make_issue(async_db, user_id=user.id, issue_number="6", position=1)
    source_list_id = await _seed_source_list(
        async_db,
        issues=[missing, unapproved],
        omit_identity_at={1, 2},
    )
    source_entries = list(
        (
            await async_db.scalars(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == source_list_id)
                .order_by(CBLSourceEntry.position)
            )
        ).all()
    )
    decisions = {str(source_entries[0].id): True}
    plan_response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-plan",
        json={"series_decisions": {}, "entry_decisions": decisions},
    )
    payload = _commit_payload(plan_response.json(), entry_decisions=decisions)
    first = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit", json=payload
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["created_issue_ids"]) == 1
    assert len(first_body["created_thread_ids"]) == 1
    assert first_body["excluded_source_positions"] == [2]
    assert first_body["final_adopted_source_positions"] == [1]

    second = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit", json=payload
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["idempotent_replay"] is True
    assert second_body["created_issue_ids"] == []
    assert second_body["group_id"] == first_body["group_id"]
    assert second_body["memberships"] == first_body["memberships"]

    membership = await async_db.get(
        DependencyGroupMembership, second_body["memberships"][0]["membership_id"]
    )
    assert membership is not None
    membership.sequence_order = 99
    await async_db.flush()
    repaired = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit", json=payload
    )
    assert repaired.status_code == 200, repaired.text
    assert repaired.json()["idempotent_replay"] is False
    assert repaired.json()["memberships"][0]["sequence_order"] == 1


@pytest.mark.asyncio
async def test_commit_groups_three_missing_issues_into_one_stable_series_thread(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """One proven run creates one thread, ordered issues, and gapped CBL memberships."""
    user = await get_or_create_user_async(async_db)
    placeholders = [
        await _make_issue(async_db, user_id=user.id, issue_number=number, position=1)
        for number in ("3", "1", "2")
    ]
    list_id = await _seed_source_list(
        async_db,
        issues=placeholders,
        omit_identity_at={1, 2, 3},
    )
    entries = list(
        (
            await async_db.scalars(
                select(CBLSourceEntry)
                .where(CBLSourceEntry.list_id == list_id)
                .order_by(CBLSourceEntry.position)
            )
        ).all()
    )
    for entry, position in zip(reversed(entries), (9, 5, 2), strict=True):
        entry.position = position
        await async_db.flush()
    decisions = {str(entry.id): True for entry in entries}
    preview = (
        await auth_client.post(
            f"/api/v1/issue-identity/cbl/{list_id}/adoption-plan",
            json={"series_decisions": {}, "entry_decisions": decisions},
        )
    ).json()
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{list_id}/adoption-commit",
        json=_commit_payload(preview, entry_decisions=decisions),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["created_thread_ids"]) == 1
    assert len(body["created_issue_ids"]) == 3
    created = list(
        (
            await async_db.scalars(
                select(Issue)
                .where(Issue.thread_id == body["created_thread_ids"][0])
                .order_by(Issue.position)
            )
        ).all()
    )
    assert [(issue.issue_number, issue.position) for issue in created] == [
        ("1", 1),
        ("2", 2),
        ("3", 3),
    ]
    assert [member["sequence_order"] for member in body["memberships"]] == [2, 5, 9]
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(IssueExternalIdentityMapping)
            .where(
                IssueExternalIdentityMapping.issue_id.in_(body["created_issue_ids"]),
                IssueExternalIdentityMapping.status == "confirmed",
            )
        )
        == 3
    )
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(ThreadExternalSeriesMapping)
            .where(
                ThreadExternalSeriesMapping.thread_id == body["created_thread_ids"][0],
                ThreadExternalSeriesMapping.status == "confirmed",
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_commit_reuses_confirmed_series_thread_and_rejects_missing_series_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Confirmed external identity proves reuse; absent series evidence rolls back."""
    user = await get_or_create_user_async(async_db)
    placeholder = await _make_issue(async_db, user_id=user.id, issue_number="20", position=1)
    list_id = await _seed_source_list(async_db, issues=[placeholder], omit_identity_at={1})
    entry = await async_db.scalar(
        select(CBLSourceEntry).where(CBLSourceEntry.list_id == list_id)
    )
    assert entry is not None and entry.external_series_identity_id is not None
    target = Thread(
        title="Canonical run",
        format="Comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=20,
        status="active",
        reading_progress="in_progress",
        user_id=user.id,
    )
    async_db.add(target)
    await async_db.flush()
    read_at = datetime.now(UTC)
    existing = Issue(
        thread_id=target.id,
        issue_number="21",
        position=1,
        status="read",
        read_at=read_at,
    )
    async_db.add(existing)
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=target.id,
            external_identity_id=entry.external_series_identity_id,
            status="confirmed",
        )
    )
    await async_db.flush()
    decisions = {str(entry.id): True}
    preview = (
        await auth_client.post(
            f"/api/v1/issue-identity/cbl/{list_id}/adoption-plan",
            json={"series_decisions": {}, "entry_decisions": decisions},
        )
    ).json()
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{list_id}/adoption-commit",
        json=_commit_payload(preview, entry_decisions=decisions),
    )
    assert response.status_code == 200, response.text
    assert response.json()["created_thread_ids"] == []
    created = await async_db.get(Issue, response.json()["created_issue_ids"][0])
    preserved = await async_db.get(Issue, existing.id)
    assert created is not None and created.thread_id == target.id and created.position == 1
    assert preserved is not None
    assert (preserved.id, preserved.position, preserved.status, preserved.read_at) == (
        existing.id,
        2,
        "read",
        read_at,
    )

    missing_series = await _make_issue(async_db, user_id=user.id, issue_number="4", position=1)
    missing_list_id = await _seed_source_list(
        async_db,
        issues=[missing_series],
        source_path="No-series.cbl",
        omit_identity_at={1},
        omit_series_identity_at={1},
    )
    missing_entry = await async_db.scalar(
        select(CBLSourceEntry).where(CBLSourceEntry.list_id == missing_list_id)
    )
    assert missing_entry is not None
    missing_decisions = {str(missing_entry.id): True}
    missing_preview = (
        await auth_client.post(
            f"/api/v1/issue-identity/cbl/{missing_list_id}/adoption-plan",
            json={"series_decisions": {}, "entry_decisions": missing_decisions},
        )
    ).json()
    counts = (
        await async_db.scalar(select(func.count()).select_from(Thread)),
        await async_db.scalar(select(func.count()).select_from(Issue)),
    )
    rejected = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{missing_list_id}/adoption-commit",
        json=_commit_payload(missing_preview, entry_decisions=missing_decisions),
    )
    assert rejected.status_code == 422
    assert counts == (
        await async_db.scalar(select(func.count()).select_from(Thread)),
        await async_db.scalar(select(func.count()).select_from(Issue)),
    )


@pytest.mark.asyncio
async def test_missing_issue_merge_inserts_several_holes(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing issues fill normalized holes while existing issue rows survive."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Run",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()
    existing = [
        Issue(thread_id=thread.id, issue_number="2", position=1, status="unread"),
        Issue(thread_id=thread.id, issue_number="5", position=2, status="unread"),
    ]
    async_db.add_all(existing)
    await async_db.flush()
    original_ids = [issue.id for issue in existing]

    async def confirm_identity(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(cbl_service, "confirm_comicvine_identity", confirm_identity)
    await cbl_service._append_missing_issues(
        async_db,
        user_id=user.id,
        thread=thread,
        entries=[
            {"issue_number": "1", "cbl_position": 3, "comicvine_issue_id": "101"},
            {"issue_number": "3", "cbl_position": 8, "comicvine_issue_id": "103"},
            {"issue_number": "4", "cbl_position": 13, "comicvine_issue_id": "104"},
        ],
    )
    ordered = list(
        (
            await async_db.scalars(
                select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
            )
        ).all()
    )
    assert [(issue.issue_number, issue.position) for issue in ordered] == [
        ("1", 1),
        ("2", 2),
        ("3", 3),
        ("4", 4),
        ("5", 5),
    ]
    assert [ordered[1].id, ordered[4].id] == original_ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("existing_numbers", "new_number", "message"),
    [
        (("2", "1"), "3", "strict normalized order"),
        (("1", "2"), "1.0", "duplicate normalized issue numbers"),
    ],
)
async def test_missing_issue_merge_fails_closed_on_ambiguous_order(
    async_db: AsyncSession,
    existing_numbers: tuple[str, str],
    new_number: str,
    message: str,
) -> None:
    """Inconsistent existing order and normalized collisions fail before insertion."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Unsafe run",
        format="Comic",
        issues_remaining=2,
        total_issues=2,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()
    async_db.add_all(
        [
            Issue(
                thread_id=thread.id,
                issue_number=number,
                position=position,
                status="unread",
            )
            for position, number in enumerate(existing_numbers, start=1)
        ]
    )
    await async_db.flush()

    with pytest.raises(CBLAdoptionMaterializationError, match=message):
        await cbl_service._append_missing_issues(
            async_db,
            user_id=user.id,
            thread=thread,
            entries=[
                {
                    "issue_number": new_number,
                    "cbl_position": 7,
                    "comicvine_issue_id": "1007",
                }
            ],
        )


@pytest.mark.asyncio
async def test_commit_rejects_stale_fingerprint_and_identity_without_mutation(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Both source and canonical-plan drift fail before materialization."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    source_list_id = await _seed_source_list(async_db, issues=[issue])
    preview = (
        await auth_client.get(
            f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-preview"
        )
    ).json()
    baseline_groups = await async_db.scalar(select(func.count()).select_from(DependencyGroup))

    stale_source = _commit_payload(preview)
    source = stale_source["source"]
    assert isinstance(source, dict)
    source["content_hash"] = "old-hash"
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit", json=stale_source
    )
    assert response.status_code == 409
    assert "source_fingerprint_changed" in response.json()["detail"]["reasons"]

    source_entry = await async_db.scalar(
        select(CBLSourceEntry).where(CBLSourceEntry.list_id == source_list_id)
    )
    assert source_entry is not None and source_entry.external_series_identity_id is not None
    series_identity = await async_db.get(
        ExternalIdentity, source_entry.external_series_identity_id
    )
    assert series_identity is not None
    series_identity.external_id = "changed-stable-run"
    await async_db.flush()
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit",
        json=_commit_payload(preview),
    )
    assert response.status_code == 409
    assert any(
        reason.startswith("entry_material_facts_changed:")
        for reason in response.json()["detail"]["reasons"]
    )

    mapping = await async_db.scalar(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    )
    assert mapping is not None
    await async_db.delete(mapping)
    await async_db.flush()
    response = await auth_client.post(
        f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit",
        json=_commit_payload(preview),
    )
    assert response.status_code == 409
    assert any(
        reason.startswith("entry_material_facts_changed:")
        for reason in response.json()["detail"]["reasons"]
    )
    assert baseline_groups == await async_db.scalar(
        select(func.count()).select_from(DependencyGroup)
    )


@pytest.mark.asyncio
async def test_commit_rolls_back_when_blocker_refresh_fails(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late failure leaves no imported issue, thread, group, or membership."""
    user = await get_or_create_user_async(async_db)
    missing = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    source_list_id = await _seed_source_list(
        async_db, issues=[missing], omit_identity_at={1}
    )
    entry = await async_db.scalar(
        select(CBLSourceEntry).where(CBLSourceEntry.list_id == source_list_id)
    )
    assert entry is not None
    decisions = {str(entry.id): True}
    preview = (
        await auth_client.post(
            f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-plan",
            json={"series_decisions": {}, "entry_decisions": decisions},
        )
    ).json()
    counts_before = (
        await async_db.scalar(select(func.count()).select_from(Issue)),
        await async_db.scalar(select(func.count()).select_from(Thread)),
        await async_db.scalar(select(func.count()).select_from(DependencyGroup)),
        await async_db.scalar(select(func.count()).select_from(DependencyGroupMembership)),
    )

    async def fail_refresh(_user_id: int, _db: AsyncSession) -> dict[int, bool]:
        assert (
            await _db.scalar(
                select(func.count()).select_from(DependencyGroupMembership)
            )
        ) == (counts_before[3] or 0) + 1
        raise RuntimeError("forced refresh failure")

    monkeypatch.setattr(cbl_service, "refresh_user_blocked_status", fail_refresh)
    with pytest.raises(RuntimeError, match="forced refresh failure"):
        await auth_client.post(
            f"/api/v1/issue-identity/cbl/{source_list_id}/adoption-commit",
            json=_commit_payload(preview, entry_decisions=decisions),
        )
    assert counts_before == (
        await async_db.scalar(select(func.count()).select_from(Issue)),
        await async_db.scalar(select(func.count()).select_from(Thread)),
        await async_db.scalar(select(func.count()).select_from(DependencyGroup)),
        await async_db.scalar(select(func.count()).select_from(DependencyGroupMembership)),
    )


@pytest.mark.asyncio
async def test_concurrent_same_source_adoption_converges_without_duplicates(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """The source lock serializes concurrent commits onto one group and order."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, issue_number="1", position=1)
    source_list_id = await _seed_source_list(async_db, issues=[issue])
    report, plan = await preview_cbl_adoption(
        async_db, user_id=user.id, list_id=source_list_id
    )
    await async_db.commit()
    source = CBLReviewedSource(
        source_list_id=source_list_id,
        source_repository=str(report.source_repository),
        source_path=str(report.source_path),
        content_hash=str(report.content_hash),
        revision_sha=str(report.revision_sha),
    )
    reviewed = tuple(
        CBLReviewedEntry(
            cbl_position=int(entry["cbl_position"]),
            cbl_entry_id=int(entry["cbl_entry_id"]),
            series_group_id=str(entry["series_group_id"]),
            series_provider=cast(str | None, entry.get("series_provider")),
            series_external_id=cast(str | None, entry.get("series_external_id")),
            comicvine_series_id=cast(str | None, entry.get("comicvine_series_id")),
            adoption_class=str(entry["adoption_class"]),
            adoption_decision=str(entry["adoption_decision"]),
            adopted=bool(entry["adopted"]),
            comicvine_issue_id=str(entry["comicvine_issue_id"]),
            resolved_issue_id=int(entry["resolved_issue_id"]),
            canonical_issue_id=int(entry["canonical_issue_id"]),
            resolution_status=str(entry["resolution_status"]),
        )
        for entry in plan.entries
    )
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def adopt() -> int:
        async with session_factory() as session:
            result = await commit_cbl_adoption(
                session,
                user_id=user.id,
                list_id=source_list_id,
                source=source,
                reviewed_entries=reviewed,
                reviewed_final_positions=plan.final_adopted_order,
                series_decisions={},
                entry_decisions={},
            )
            await session.commit()
            return result.group_id

    group_ids = await asyncio.gather(adopt(), adopt())
    assert group_ids[0] == group_ids[1]
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(DependencyGroup)
            .where(
                DependencyGroup.user_id == user.id,
                DependencyGroup.cbl_source_list_id == source_list_id,
            )
        )
        == 1
    )
    memberships = list(
        (
            await async_db.scalars(
                select(DependencyGroupMembership).where(
                    DependencyGroupMembership.group_id == group_ids[0]
                )
            )
        ).all()
    )
    assert [(row.issue_id, row.sequence_order) for row in memberships] == [(issue.id, 1)]


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
