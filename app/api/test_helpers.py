"""Test API endpoints for E2E testing."""

import os
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Issue, Session as SessionModel, Thread, User
from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.reading_order import ReadingOrder, ReadingOrderItem

router = APIRouter(prefix="/test", tags=["test"])


async def _require_test_environment() -> None:
    """Reject test-only endpoints outside the E2E environment."""
    if os.getenv("TEST_ENVIRONMENT") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )


@router.post("/reading-orders")
async def create_test_reading_order(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Create a reading order (with optional items) for E2E tests.

    Only available in test environments. Accepts a name and a list of
    thread_id/position items so browser tests can seed projection targets.
    """
    await _require_test_environment()

    name = str(payload.get("name") or "Test reading order")
    order = ReadingOrder(name=name, user_id=current_user.id)
    db.add(order)
    await db.flush()

    raw_items = payload.get("items")
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            raw_thread_id = raw.get("thread_id")
            raw_position = raw.get("position")
            db.add(
                ReadingOrderItem(
                    reading_order_id=order.id,
                    thread_id=int(raw_thread_id) if raw_thread_id is not None else 0,
                    position=int(raw_position) if raw_position is not None else 1,
                    issue_number=raw.get("issue_number"),
                )
            )
    await db.commit()
    await db.refresh(order)

    return {"id": order.id, "name": order.name}


@router.post("/issue-identity")
async def create_test_issue_identity(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Confirm a synthetic ComicVine identity with rich metadata for owned issues.

    Browser fixtures need deterministic cover/series rendering without the
    upstream ComicVine provider. This test-only helper persists a confirmed
    identity (with a complete provider payload so inline hydration is never
    triggered) for one issue or every issue of one owned thread.

    Args:
        payload: ``issue_id`` or ``thread_id``, plus optional ``series_name``,
            ``series_id`` and ``image_url``.
        current_user: Owner of the issues being re-identified.
        db: Database session.

    Returns:
        Affected issue ids plus the resolved series name and id.

    Raises:
        HTTPException: Outside test environments, or when the referenced
            issue/thread does not exist or is not owned by the caller.
    """
    await _require_test_environment()

    raw_issue_id = payload.get("issue_id")
    raw_thread_id = payload.get("thread_id")
    if raw_issue_id is None and raw_thread_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either issue_id or thread_id",
        )

    issues: list[Issue] = []
    if raw_thread_id is not None:
        thread = (
            await db.execute(
                select(Thread).where(
                    Thread.id == int(raw_thread_id),
                    Thread.user_id == current_user.id,
                )
            )
        ).scalar_one_or_none()
        if thread is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Thread {raw_thread_id} not found",
            )
        issues = list(
            (await db.execute(select(Issue).where(Issue.thread_id == thread.id))).scalars()
        )
    else:
        issue = (
            await db.execute(select(Issue).where(Issue.id == int(raw_issue_id)))
        ).scalar_one_or_none()
        if issue is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue {raw_issue_id} not found",
            )
        owner = (
            await db.execute(select(Thread).where(Thread.id == issue.thread_id))
        ).scalar_one_or_none()
        if owner is None or owner.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Issue {raw_issue_id} not found",
            )
        issues = [issue]

    if not issues:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No issues matched the requested fixture scope",
        )

    series_name = str(payload.get("series_name") or "Fixture Crossover").strip()
    if not series_name:
        series_name = "Fixture Crossover"
    series_id = int(payload.get("series_id") or (700_000 + len(series_name) * 31))
    image_value = payload.get("image_url")
    image_url = str(image_value) if image_value else None

    affected_ids: list[int] = []
    for issue in sorted(issues, key=lambda candidate: (candidate.position, candidate.id)):
        issue_number = str(issue.issue_number)
        cv_issue_id = f"4000-{900_000_000 + issue.id}"
        provider_payload: dict[str, object] = {
            "id": cv_issue_id,
            "name": f"{series_name} #{issue_number}",
            "issue_number": issue_number,
            "cover_date": "2025-06-01",
            "store_date": "2025-06-01",
            "image": {"original_url": image_url, "medium_url": image_url} if image_url else {},
            "volume": {"id": series_id, "name": series_name},
            "person_credits": [
                {"name": "Fixture Writer", "role": "writer"},
                {"name": "Fixture Penciller", "role": "penciler"},
            ],
            "character_credits": [],
            "team_credits": [],
            "story_arc_credits": [],
            "date_last_updated": datetime.now(UTC).isoformat(),
        }
        metadata: dict[str, object] = {
            "raw_provider_payload": provider_payload,
            **provider_payload,
            "series_id": series_id,
            "series_name": series_name,
        }
        if image_url:
            metadata["image_url"] = image_url

        identity = (
            await db.execute(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == "comicvine",
                    ExternalIdentity.entity_type == "issue",
                    ExternalIdentity.external_id == cv_issue_id,
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=cv_issue_id,
                external_url=f"https://comicvine.gamespot.com/api/issue/{cv_issue_id}/",
                metadata_json=metadata,
            )
            db.add(identity)
        else:
            identity.metadata_json = metadata
            identity.updated_at = datetime.now(UTC)
        await db.flush()

        mapping = (
            await db.execute(
                select(IssueExternalIdentityMapping).where(
                    IssueExternalIdentityMapping.issue_id == issue.id,
                    IssueExternalIdentityMapping.external_identity_id == identity.id,
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            mapping = IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="e2e-fixture",
            )
            db.add(mapping)
        else:
            mapping.status = "confirmed"
        affected_ids.append(issue.id)

    await db.commit()

    return {
        "issue_ids": affected_ids,
        "series_name": series_name,
        "series_id": series_id,
    }


@router.post("/cbl-source")
async def create_test_cbl_source(
    payload: dict[str, object],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Seed one discoverable CBL source list for browser golden-path coverage.

    Entries may reference owned issues (existing) or ComicVine identities that are
    not mapped to any owned issue (missing_importable). This endpoint never creates
    production migration state.
    """
    await _require_test_environment()

    name = str(payload.get("name") or "Fixture CBL Source").strip() or "Fixture CBL Source"
    source_path = str(payload.get("source_path") or f"Fixtures/{name}.cbl")
    content_hash = str(payload.get("content_hash") or f"fixture-{current_user.id}-{name}")
    revision_sha = str(payload.get("revision_sha") or "fixture-revision")
    repository = str(
        payload.get("repository")
        or f"JoshCLWren/CBL-ReadingLists-fixture-{current_user.id}-{datetime.now(UTC).timestamp()}"
    )
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a non-empty entries list",
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
        declared_issue_count=len(raw_entries),
        content_hash=content_hash,
        revision_sha=revision_sha,
        active=True,
    )
    db.add(source_list)
    await db.flush()

    created_entries: list[dict[str, object]] = []
    for index, raw in enumerate(raw_entries, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"entries[{index - 1}] must be an object",
            )
        position = int(raw.get("position") or index)
        series_name = str(raw.get("series_name") or f"Fixture Series {position}")
        issue_number = str(raw.get("issue_number") or "1")
        volume_year_raw = raw.get("volume_year")
        volume_year = int(volume_year_raw) if volume_year_raw is not None else None
        issue_id_raw = raw.get("issue_id")
        comicvine_id = str(
            raw.get("comicvine_issue_id") or f"4000-fixture-{current_user.id}-{position}"
        )

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

        if issue_id_raw is not None:
            issue = (
                await db.execute(select(Issue).where(Issue.id == int(issue_id_raw)))
            ).scalar_one_or_none()
            if issue is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Issue {issue_id_raw} not found",
                )
            owner = (
                await db.execute(select(Thread).where(Thread.id == issue.thread_id))
            ).scalar_one_or_none()
            if owner is None or owner.user_id != current_user.id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Issue {issue_id_raw} not found",
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
            {
                "position": position,
                "series_name": series_name,
                "issue_number": issue_number,
                "comicvine_issue_id": comicvine_id,
                "issue_id": int(issue_id_raw) if issue_id_raw is not None else None,
            }
        )

    await db.commit()
    return {
        "id": source_list.id,
        "name": source_list.name,
        "source_path": source_list.source_path,
        "content_hash": source_list.content_hash,
        "revision_sha": source_list.revision_sha,
        "entries": created_entries,
    }


@router.post("/sessions/expire")
async def expire_current_session(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """Expire the current active session by setting started_at to an old timestamp.

    This endpoint is only available in test environment and is used for E2E testing
    of session expiry notifications.

    Args:
        current_user: The authenticated user making the request.
        db: SQLAlchemy session for database operations.

    Returns:
        Dictionary with success message.

    Raises:
        HTTPException: If not in test environment or no active session found.
    """
    await _require_test_environment()

    session_result = await db.execute(
        select(SessionModel)
        .where(SessionModel.user_id == current_user.id)
        .where(SessionModel.ended_at.is_(None))
    )
    session = session_result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active session found",
        )

    session.ended_at = datetime.now(UTC)
    await db.commit()

    return {"status": "success", "message": "Session expired"}
