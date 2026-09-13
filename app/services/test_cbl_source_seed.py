"""Test-environment CBL source seeding for browser golden-path coverage."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.test_fixtures import (
    TestCblSourceCreate,
    TestCblSourceEntryResponse,
    TestCblSourceResponse,
)


async def create_test_cbl_source(
    db: AsyncSession,
    *,
    user_id: int,
    payload: TestCblSourceCreate,
) -> TestCblSourceResponse:
    """Seed one discoverable CBL source list for the authenticated test user.

    Entries may reference owned issues or ComicVine identities that are not yet
    mapped to owned comics. This never creates production migration state.
    """
    name = (payload.name or "Fixture CBL Source").strip() or "Fixture CBL Source"
    source_path = payload.source_path or f"Fixtures/{name}.cbl"
    content_hash = payload.content_hash or f"fixture-{user_id}-{name}"
    revision_sha = payload.revision_sha or "fixture-revision"
    repository = payload.repository or (
        f"JoshCLWren/CBL-ReadingLists-fixture-{user_id}-{datetime.now(UTC).timestamp()}"
    )

    source = CBLSource(
        repository=repository,
        revision_sha=revision_sha,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=source_path,
        name=name,
        declared_issue_count=len(payload.entries),
        content_hash=content_hash,
        revision_sha=revision_sha,
        active=True,
    )
    db.add(source_list)
    await db.flush()

    created_entries: list[TestCblSourceEntryResponse] = []
    for index, raw in enumerate(payload.entries, start=1):
        position = raw.position or index
        series_name = raw.series_name or f"Fixture Series {position}"
        issue_number = raw.issue_number or "1"
        volume_year = raw.volume_year
        comicvine_id = raw.comicvine_issue_id or f"4000-fixture-{user_id}-{position}"

        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=comicvine_id,
            metadata_json={
                "volume": {
                    "name": series_name,
                    "start_year": volume_year,
                }
            },
        )
        db.add(identity)
        await db.flush()

        if raw.issue_id is not None:
            issue = (
                await db.execute(select(Issue).where(Issue.id == raw.issue_id))
            ).scalar_one_or_none()
            if issue is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Issue {raw.issue_id} not found",
                )
            owner = (
                await db.execute(select(Thread).where(Thread.id == issue.thread_id))
            ).scalar_one_or_none()
            if owner is None or owner.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Issue {raw.issue_id} not found",
                )
            db.add(
                IssueExternalIdentityMapping(
                    issue_id=issue.id,
                    external_identity_id=identity.id,
                    status="confirmed",
                    evidence_source="e2e-fixture",
                )
            )

        db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=position,
                series_name=series_name,
                issue_number=issue_number,
                volume_year=volume_year,
                external_issue_identity_id=identity.id,
            )
        )
        created_entries.append(
            TestCblSourceEntryResponse(
                position=position,
                series_name=series_name,
                issue_number=issue_number,
                comicvine_issue_id=comicvine_id,
                issue_id=raw.issue_id,
            )
        )

    await db.commit()
    return TestCblSourceResponse(
        id=source_list.id,
        name=source_list.name,
        source_path=source_list.source_path,
        content_hash=source_list.content_hash,
        revision_sha=source_list.revision_sha,
        entries=created_entries,
    )
