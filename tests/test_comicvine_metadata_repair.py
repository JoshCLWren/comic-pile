"""Regression coverage for durable repair persistence and worker outcomes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.cron import comicvine_metadata_repair_cron
from app.models.external_identity import ExternalIdentity
from app.repositories.comicvine_metadata_refresh_repository import get_request
from app.schemas.comicvine import MetadataRepairDrainResponse
from app.services import comicvine_metadata_repair as repair
from fastapi import Response


@pytest.mark.asyncio
async def test_repair_is_idempotent_and_unconfigured_worker_defers(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated reads share durable work that survives an unavailable provider."""
    now = datetime.now(UTC)
    identity = ExternalIdentity(
        provider="comicvine", entity_type="issue", external_id="repair-fixture",
        metadata_json={}, updated_at=now,
    )
    async_db.add(identity)
    await async_db.flush()
    identity.external_id = str(identity.id)
    identity_id = identity.id
    first = await repair.request_issue_metadata_repair(async_db, identity_id, now=now)
    second = await repair.request_issue_metadata_repair(async_db, identity_id, now=now)
    assert first.refresh_requested is True
    assert second.refresh_requested is False
    await async_db.commit()
    monkeypatch.setattr(repair, "_build_comicvine_client", lambda: None)
    report = await repair.drain_due_metadata_repairs(db=async_db, now=now)
    assert report.claimed == 1
    assert report.deferred == 1
    request = await get_request(async_db, identity_id)
    assert request is not None
    assert request.state == "deferred"
    assert request.last_error == "provider_not_configured"
    assert request.next_attempt_at > now
    assert (await repair.drain_due_metadata_repairs(db=async_db, now=now)).claimed == 0


@pytest.mark.asyncio
async def test_cron_returns_schema_and_delegates_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router projects a service report without committing the database."""
    db = AsyncMock(spec=AsyncSession)
    drain = AsyncMock(return_value=repair.MetadataRepairDrainReport(claimed=2, completed=2))
    monkeypatch.setattr("app.api.cron.drain_due_metadata_repairs", drain)
    response = Response()
    result = await comicvine_metadata_repair_cron(db, response)
    assert isinstance(result, MetadataRepairDrainResponse)
    assert result.claimed == result.completed == 2
    assert response.headers["Cache-Control"] == "no-store"
    drain.assert_awaited_once_with(db=db)
    db.commit.assert_not_awaited()


def test_schedule_without_loop_does_not_create_coroutine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declining a background drain must not leak an unawaited coroutine."""
    drain = AsyncMock()
    monkeypatch.setattr(repair, "drain_due_metadata_repairs", drain)
    monkeypatch.setattr(repair, "_drain_task", None)
    assert repair.schedule_metadata_repair_drain() is False
    drain.assert_not_called()
