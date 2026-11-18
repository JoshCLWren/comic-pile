"""CBL identity resolution never omits unmatched rows or picks min issue id."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceList
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.models.issue import Issue
from app.services.source_backed_reader_order_migration import (
    PRODUCTION_SOURCE_BACKED_SPECS,
    apply_source_backed_reader_order_migration,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError


async def _source_list(db: AsyncSession, *, name: str, count: int) -> CBLSourceList:
    source = CBLSource(
        repository=f"test/cbl-identity-{name}-{count}-{datetime.now(UTC).timestamp()}",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Marvel/identity.cbl",
        name=name,
        declared_issue_count=count,
        content_hash="c" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    db.add(source_list)
    await db.flush()
    return source_list


async def _identity(db: AsyncSession, *, entity_type: str, external_id: str) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type=entity_type,
        external_id=external_id,
        metadata_json={"cover_date": "1998-12-01", "volume_id": "26316"},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _map_issue(
    db: AsyncSession,
    *,
    issue: Issue,
    identity: ExternalIdentity,
) -> None:
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )


@pytest.mark.asyncio
async def test_xmen_ff_cannot_apply_as_strict_source_backed_plans(
    async_db: AsyncSession,
) -> None:
    """Imported X-Men/FF CBL lists must not compile inferred gates."""
    for key in ("x-men-era-ten", "fantastic-four-early-years"):
        with pytest.raises(MigrationInvariantError, match="held until CBL identity"):
            await apply_source_backed_reader_order_migration(
                async_db,
                snapshot={},
                spec=PRODUCTION_SOURCE_BACKED_SPECS[key],
            )
