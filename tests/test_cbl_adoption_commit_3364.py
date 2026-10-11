"""Regression coverage for CBL adoption-commit 500s (#3364).

Reproduces the prod failure: a large CBL list with many already-owned issues,
one ambiguous entry, and a repeated missing identity. The one-decision
``POST /api/v1/cbl/{list_id}/adoption-commit`` path must return 201 and create
exactly one Reading Plan (or a specific 4xx), never a generic 500.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cbl_plan_adoption import api_cbl_adoption_commit
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.cbl_adoption import CBLAdoptionCommitRequest
from tests.conftest import get_or_create_user_async


LIST_NAME = "[Marvel] [2024-2026] The New Marvel Ultimate Universe 2.0 (CBH)"
SOURCE_PATH = "Marvel/The New Marvel Ultimate Universe 2.0.cbl"

# Series mix modeled on the Ultimate Universe 2.0 reading order: owned via
# ComicVine, owned via title+number fallback (#3348), unique missing, one
# repeated missing identity, one repeated owned identity, one ambiguous.
_SERIES_SPECS: tuple[tuple[str, int, int, int], ...] = (
    ("Ultimate Spider-Man", 25, 6, 5),
    ("Ultimate X-Men", 25, 6, 4),
    ("The Ultimates", 20, 6, 4),
    ("Ultimate Black Panther", 10, 12, 4),
)


async def _thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> Thread:
    """Create one owned series thread."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=0,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _issue(
    db: AsyncSession,
    *,
    thread: Thread,
    issue_number: str,
    position: int,
) -> Issue:
    """Create one owned issue on ``thread``."""
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.total_issues = (thread.total_issues or 0) + 1
    thread.issues_remaining = (thread.issues_remaining or 0) + 1
    if thread.next_unread_issue_id is None:
        thread.next_unread_issue_id = issue.id
    return issue


async def _identity(db: AsyncSession, *, entity_type: str, external_id: str) -> ExternalIdentity:
    """Persist one ComicVine identity row."""
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type=entity_type,
        external_id=external_id,
        metadata_json={},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _seed_ultimate_universe_list(db: AsyncSession, *, user_id: int) -> CBLSourceList:
    """Seed the 130-entry Ultimate Universe 2.0 mix used in the prod repro.

    Layout:
    * 80 ComicVine-mapped owned issues
    * 30 title+number fallback owned issues
    * 1 extra CBL position repeating an already-owned ComicVine identity
    * 17 unique missing/importable issues
    * 1 extra CBL position repeating a missing ComicVine identity
    * 1 ambiguous title+number collision
    """
    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists-3364",
        revision_sha="uu-2.0-3364",
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=SOURCE_PATH,
        name=LIST_NAME,
        declared_issue_count=130,
        content_hash="uu-2.0-content-3364",
        revision_sha="uu-2.0-3364",
        active=True,
    )
    db.add(source_list)
    await db.flush()

    position = 1
    queue_position = 1
    first_owned_identity: ExternalIdentity | None = None
    first_missing_identity: ExternalIdentity | None = None
    first_missing_series_identity: ExternalIdentity | None = None
    first_missing_series_name = ""
    first_missing_issue_number = ""

    for series_name, mapped_count, fallback_count, missing_count in _SERIES_SPECS:
        thread = await _thread(
            db,
            user_id=user_id,
            title=series_name,
            queue_position=queue_position,
        )
        queue_position += 1
        series_identity = await _identity(
            db,
            entity_type="series",
            external_id=f"4050-3364-{series_name.replace(' ', '-').lower()}",
        )
        db.add(
            ThreadExternalSeriesMapping(
                thread_id=thread.id,
                external_identity_id=series_identity.id,
                status="confirmed",
                evidence_source="test-3364",
            )
        )
        issue_position = 1
        for _ in range(mapped_count):
            issue = await _issue(
                db,
                thread=thread,
                issue_number=str(issue_position),
                position=issue_position,
            )
            identity = await _identity(
                db,
                entity_type="issue",
                external_id=f"4000-3364-mapped-{series_name}-{issue_position}",
            )
            db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                    evidence_source="test-3364",
                )
            )
            db.add(
                CBLSourceEntry(
                    list_id=source_list.id,
                    position=position,
                    series_name=series_name,
                    issue_number=str(issue_position),
                    external_issue_identity_id=identity.id,
                    external_series_identity_id=series_identity.id,
                    volume_year=2024,
                )
            )
            if first_owned_identity is None:
                first_owned_identity = identity
            position += 1
            issue_position += 1
        for _ in range(fallback_count):
            await _issue(
                db,
                thread=thread,
                issue_number=str(issue_position),
                position=issue_position,
            )
            identity = await _identity(
                db,
                entity_type="issue",
                external_id=f"4000-3364-fallback-{series_name}-{issue_position}",
            )
            db.add(
                CBLSourceEntry(
                    list_id=source_list.id,
                    position=position,
                    series_name=series_name,
                    issue_number=str(issue_position),
                    external_issue_identity_id=identity.id,
                    external_series_identity_id=series_identity.id,
                    volume_year=2024,
                )
            )
            position += 1
            issue_position += 1
        for _ in range(missing_count):
            identity = await _identity(
                db,
                entity_type="issue",
                external_id=f"4000-3364-missing-{series_name}-{issue_position}",
            )
            db.add(
                CBLSourceEntry(
                    list_id=source_list.id,
                    position=position,
                    series_name=series_name,
                    issue_number=str(issue_position),
                    external_issue_identity_id=identity.id,
                    external_series_identity_id=series_identity.id,
                    volume_year=2024,
                )
            )
            if first_missing_identity is None:
                first_missing_identity = identity
                first_missing_series_identity = series_identity
                first_missing_series_name = series_name
                first_missing_issue_number = str(issue_position)
            position += 1
            issue_position += 1

    assert first_owned_identity is not None
    assert first_missing_identity is not None
    assert first_missing_series_identity is not None

    # Repeated already-owned issue: same ComicVine identity, second CBL slot.
    db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=position,
            series_name="Ultimate Spider-Man",
            issue_number="1",
            external_issue_identity_id=first_owned_identity.id,
            external_series_identity_id=first_missing_series_identity.id,
            volume_year=2024,
        )
    )
    position += 1

    # Repeated missing identity: same ComicVine ID listed twice. Creating the
    # second copy hits uq_issue_thread_number unless adoption reuses the first.
    db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=position,
            series_name=first_missing_series_name,
            issue_number=first_missing_issue_number,
            external_issue_identity_id=first_missing_identity.id,
            external_series_identity_id=first_missing_series_identity.id,
            volume_year=2024,
        )
    )
    position += 1

    wolf_a = await _thread(
        db,
        user_id=user_id,
        title="Ultimate Wolverine",
        queue_position=queue_position,
    )
    wolf_b = await _thread(
        db,
        user_id=user_id,
        title="ultimate  wolverine",
        queue_position=queue_position + 1,
    )
    await _issue(db, thread=wolf_a, issue_number="1", position=1)
    await _issue(db, thread=wolf_b, issue_number="1", position=1)
    ambiguous_identity = await _identity(
        db,
        entity_type="issue",
        external_id="4000-3364-ambiguous-wolverine-1",
    )
    db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=position,
            series_name="Ultimate Wolverine",
            issue_number="1",
            external_issue_identity_id=ambiguous_identity.id,
            volume_year=2025,
        )
    )
    await db.commit()
    return source_list


@pytest.mark.asyncio
async def test_adoption_commit_realistic_uu_list_returns_201_not_500(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """#3364: the prod UU 2.0 mix must create a plan, never a generic 500."""
    user = await get_or_create_user_async(async_db)
    source_list = await _seed_ultimate_universe_list(async_db, user_id=user.id)

    preview_response = await auth_client.get(
        f"/api/v1/issue-identity/cbl/{source_list.id}/adoption-preview"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    summary = preview["summary"]
    assert preview["total_positions"] == 130
    assert summary["reused_existing_count"] == 111
    assert summary["missing_would_create_count"] == 18
    assert summary["unresolved_count"] == 1

    plans_before = await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan).where(ContinuityPlan.user_id == user.id)
    )
    issues_before = await async_db.scalar(select(func.count()).select_from(Issue))

    payload = {
        "entry_decisions": {},
        "series_decisions": [],
        "series_overrides": [],
        "content_hash": preview["source"]["content_hash"],
        "revision_sha": preview["source"]["revision_sha"],
    }
    commit = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/adoption-commit",
        json=payload,
    )
    assert commit.status_code != 500, commit.text
    assert commit.status_code == 201, commit.text
    body = commit.json()
    assert body["name"] == LIST_NAME
    assert body["id"] > 0
    assert 130 in body["unresolved_positions"]
    assert body["unresolved_positions"] == [130]
    # 111 already-owned positions include one repeated identity; the repeated
    # missing identity reuses the first materialized issue instead of inserting
    # a second row that would trip uq_issue_thread_number.
    assert len(body["reused_positions"]) == 112
    assert len(body["created_positions"]) == 17
    issue_refs = [node["ref_id"] for node in body["nodes"] if node["node_type"] == "issue"]
    assert len(issue_refs) == len(set(issue_refs))
    assert len(issue_refs) == 110 + 17

    plans_after = await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan).where(ContinuityPlan.user_id == user.id)
    )
    assert plans_after == (plans_before or 0) + 1
    issues_after = await async_db.scalar(select(func.count()).select_from(Issue))
    assert issues_after == (issues_before or 0) + 17

    replay = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/adoption-commit",
        json=payload,
    )
    assert replay.status_code == 201, replay.text
    replayed = replay.json()
    assert replayed["id"] == body["id"]
    assert replayed["created_positions"] == []
    assert len(replayed["nodes"]) == len(body["nodes"])
    assert await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan).where(ContinuityPlan.user_id == user.id)
    ) == plans_after
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == issues_after


@pytest.mark.asyncio
async def test_commit_endpoint_logs_unexpected_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """#3364: unexpected adoption exceptions must be logged with list and user."""
    request = CBLAdoptionCommitRequest(content_hash="hash", revision_sha="rev")
    current_user = MagicMock()
    current_user.id = 7
    with (
        patch(
            "app.api.cbl_plan_adoption.adopt_cbl_material_into_reading_plan",
            new_callable=AsyncMock,
            side_effect=RuntimeError("adoption exploded for logs"),
        ),
        caplog.at_level("ERROR"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await api_cbl_adoption_commit(
                list_id=42,
                request=request,
                current_user=current_user,
                db=cast(AsyncSession, MagicMock()),
            )
    assert exc_info.value.status_code == 500
    detail = cast(dict[str, object], exc_info.value.detail)
    assert detail.get("code") == "adoption_unexpected_error"
    assert detail.get("message")
    assert "adoption exploded for logs" not in str(detail.get("message", ""))
    assert "adoption exploded for logs" in caplog.text
    assert "list_id=42" in caplog.text
    assert "user_id=7" in caplog.text
