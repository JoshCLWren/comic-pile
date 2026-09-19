"""Test-environment persistence helpers for browser fixtures."""

import os
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Session as SessionModel, Thread
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.reading_order import ReadingOrder, ReadingOrderItem
from app.schemas.test_fixtures import TestCblSourceCreate, TestCblSourceResponse
from app.services.test_cbl_source_seed import create_test_cbl_source as seed_test_cbl_source


def  -> None:
    """Reject test-only persistence outside the E2E environment."""
    if os.getenv("TEST_ENVIRONMENT") != "true":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only available in test environment",
        )


async def create_test_cbl_source(
    db: AsyncSession,
    *,
    user_id: int,
    payload: TestCblSourceCreate,
) -> TestCblSourceResponse:
    """Seed one discoverable CBL source list for browser golden-path coverage.

    Delegates to the dedicated seed helper after verifying the test-only gate.
    """
    
    return await seed_test_cbl_source(db, user_id=user_id, payload=payload)


async def create_test_reading_order(
    db: AsyncSession,
    *,
    user_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    """Create a reading order and optional items for an E2E fixture."""
    

    name = str(payload.get("name") or "Test reading order")
    order = ReadingOrder(name=name, user_id=user_id)
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


async def create_test_issue_identity(
    db: AsyncSession,
    *,
    user_id: int,
    payload: dict[str, object],
) -> dict[str, object]:
    """Confirm synthetic ComicVine identities for owned E2E fixture issues."""
    

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
                    Thread.user_id == user_id,
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
        if owner is None or owner.user_id != user_id:
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


async def expire_current_session(
    current_user: object,
    db: AsyncSession,
) -> dict[str, str]:
    """Expire the current active session for an E2E notification test."""
    

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


__all__ = [
    "create_test_cbl_source",
    "create_test_issue_identity",
    "create_test_reading_order",
    "expire_current_session",
    "seed_test_cbl_source",
]
