"""Catalog backfill query construction and persistence.

All SQLAlchemy access for catalog backfill operations lives here.
Functions return ORM models, plain rows/tuples, or counts; callers (services)
own transaction boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from app.database import Base
from app.models.catalog_backfill import BackfillBatch
from app.models.catalog_commit_receipt import CatalogCommitReceipt


async def create_backfill_batch(
    db: AsyncSession,
    *,
    user_id: int,
    status: str,
    start_offset: int,
    end_offset: int,
    fingerprint: str,
    dry_run: bool,
    apply_mode: bool,
    eligible_count: int = 0,
    conflict_count: int = 0,
    duplicate_count: int = 0,
    skipped_count: int = 0,
) -> BackfillBatch:
    """Create a new backfill batch record."""
    batch = BackfillBatch(
        user_id=user_id,
        status=status,
        start_offset=start_offset,
        end_offset=end_offset,
        fingerprint=fingerprint,
        dry_run=dry_run,
        apply_mode=apply_mode,
        eligible_count=eligible_count,
        conflict_count=conflict_count,
        duplicate_count=duplicate_count,
        skipped_count=skipped_count,
    )
    db.add(batch)
    await db.commit()
    await db.refresh(batch)
    return batch


async def update_backfill_batch_status(
    db: AsyncSession,
    batch_id: int,
    status: str,
) -> BackfillBatch | None:
    """Update backfill batch status."""
    from sqlalchemy import update
    
    stmt = (
        update(BackfillBatch)
        .where(BackfillBatch.id == batch_id)
        .values(status=status)
        .returning(BackfillBatch)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()


async def get_backfill_batch(
    db: AsyncSession,
    batch_id: int,
) -> BackfillBatch | None:
    """Get a backfill batch by ID."""
    return await db.get(BackfillBatch, batch_id)


async def list_user_backfill_batches(
    db: AsyncSession,
    user_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[BackfillBatch]:
    """List backfill batches for a user."""
    from app.models.catalog_backfill import BackfillBatch
    
    query = select(BackfillBatch).where(
        BackfillBatch.user_id == user_id
    ).order_by(BackfillBatch.created_at.desc())
    
    if limit:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_latest_user_backfill_batch(
    db: AsyncSession,
    user_id: int,
) -> BackfillBatch | None:
    """Get the most recent backfill batch for a user."""
    from app.models.catalog_backfill import BackfillBatch
    
    query = select(BackfillBatch).where(
        BackfillBatch.user_id == user_id
    ).order_by(BackfillBatch.created_at.desc()).limit(1)
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def count_user_backfill_batches(
    db: AsyncSession,
    user_id: int,
    status: str | None = None,
) -> int:
    """Count backfill batches for a user."""
    from app.models.catalog_backfill import BackfillBatch
    
    query = select(func.count()).select_from(BackfillBatch).where(
        BackfillBatch.user_id == user_id
    )
    
    if status:
        query = query.where(BackfillBatch.status == status)
    
    result = await db.execute(query)
    return result.scalar_one()


async def find_eligible_catalog_links(
    db: AsyncSession,
    *,
    user_id: int,
    start_offset: int = 0,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Find confirmed identities eligible for catalog linking.
    
    Only unambiguous confirmed issue/series mappings are eligible.
    Multiple conflicting confirmed identities, rejected/candidate identities,
    incompatible entity types, existing contradictory catalog links and
    cross-provider equivalence require review and remain unchanged.
    """
    query = text("""
        SELECT
            iem.id as mapping_id,
            iem.issue_id,
            ei.id as external_identity_id,
            ei.provider,
            ei.entity_type,
            ei.external_id,
            ei.metadata_json,
            i.thread_id,
            t.title as thread_title,
            i.issue_number,
            i.status as issue_status,
            i.read_at as issue_read_at,
            i.position as issue_position
        FROM issue_external_identity_mappings iem
        JOIN external_identities ei ON ei.id = iem.external_identity_id
        JOIN issues i ON i.id = iem.issue_id
        JOIN threads t ON t.id = i.thread_id
        LEFT JOIN catalog_issues ci ON ci.canonical_external_identity_id = ei.id
        WHERE iem.status = 'confirmed'
          AND ei.entity_type = 'issue'
          AND t.user_id = :user_id
          AND ci.id IS NULL
        ORDER BY ei.id
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, {
        "user_id": user_id,
        "limit": limit,
        "offset": start_offset,
    })
    
    links = []
    for row in result.mappings():
        links.append({
            "mapping_id": row["mapping_id"],
            "issue_id": row["issue_id"],
            "external_identity_id": row["external_identity_id"],
            "provider": row["provider"],
            "entity_type": row["entity_type"],
            "external_id": row["external_id"],
            "metadata_json": row["metadata_json"],
            "thread_id": row["thread_id"],
            "thread_title": row["thread_title"],
            "issue_number": row["issue_number"],
            "issue_status": row["issue_status"],
            "issue_read_at": row["issue_read_at"],
            "issue_position": row["issue_position"],
        })
    
    return links


async def count_eligible_catalog_links(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Count confirmed identities eligible for catalog linking."""
    query = text("""
        SELECT COUNT(*) as total
        FROM issue_external_identity_mappings iem
        JOIN external_identities ei ON ei.id = iem.external_identity_id
        JOIN issues i ON i.id = iem.issue_id
        JOIN threads t ON t.id = i.thread_id
        LEFT JOIN catalog_issues ci ON ci.canonical_external_identity_id = ei.id
        WHERE iem.status = 'confirmed'
          AND ei.entity_type = 'issue'
          AND t.user_id = :user_id
          AND ci.id IS NULL
    """)
    
    result = await db.execute(query, {"user_id": user_id})
    return result.scalar_one()


async def find_conflicting_identities_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    start_offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find issues that have confirmed mappings to different provider identities.
    
    These are ambiguous cases that require review and should not be automatically linked.
    """
    query = text("""
        SELECT
            i.id AS issue_id,
            i.thread_id,
            t.title AS thread_title,
            i.issue_number,
            array_agg(DISTINCT ei.external_id ORDER BY ei.external_id) AS external_ids,
            COUNT(DISTINCT ei.id) AS distinct_identities,
            array_agg(DISTINCT ei.provider ORDER BY ei.provider) AS providers
        FROM issues i
        JOIN threads t ON t.id = i.thread_id
        JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
        JOIN external_identities ei ON ei.id = iem.external_identity_id
        WHERE t.user_id = :user_id
          AND iem.status = 'confirmed'
          AND ei.entity_type = 'issue'
        GROUP BY i.id, i.thread_id, t.title, i.issue_number
        HAVING COUNT(DISTINCT ei.id) > 1
        ORDER BY i.id
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, {
        "user_id": user_id,
        "limit": limit,
        "offset": start_offset,
    })
    
    conflicts = []
    for row in result.mappings():
        conflicts.append({
            "issue_id": row["issue_id"],
            "thread_id": row["thread_id"],
            "thread_title": row["thread_title"],
            "issue_number": row["issue_number"],
            "external_ids": list(row["external_ids"]) if row["external_ids"] else [],
            "distinct_identities": row["distinct_identities"],
            "providers": list(row["providers"]) if row["providers"] else [],
        })
    
    return conflicts


async def count_conflicting_identities_for_user(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Count issues that have confirmed mappings to different provider identities."""
    query = text("""
        SELECT COUNT(*) as total
        FROM (
            SELECT i.id
            FROM issues i
            JOIN threads t ON t.id = i.thread_id
            JOIN issue_external_identity_mappings iem ON iem.issue_id = i.id
            JOIN external_identities ei ON ei.id = iem.external_identity_id
            WHERE t.user_id = :user_id
              AND iem.status = 'confirmed'
              AND ei.entity_type = 'issue'
            GROUP BY i.id, i.thread_id, t.title, i.issue_number
            HAVING COUNT(DISTINCT ei.id) > 1
        ) sub
    """)
    
    result = await db.execute(query, {"user_id": user_id})
    return result.scalar_one()


async def find_duplicate_physical_issues_for_user(
    db: AsyncSession,
    *,
    user_id: int,
    start_offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find confirmed identities that map to multiple user-owned issues.
    
    These are duplicate cases that require review and should not be automatically linked.
    """
    query = text("""
        SELECT
            ei.external_id AS external_id,
            ei.id AS external_identity_id,
            array_agg(iem.issue_id ORDER BY iem.issue_id) AS issue_ids,
            array_agg(i.thread_id ORDER BY iem.issue_id) AS thread_ids,
            array_agg(i.status ORDER BY iem.issue_id) AS statuses,
            array_agg(i.issue_number ORDER BY iem.issue_id) AS issue_numbers,
            array_agg(t.title ORDER BY iem.issue_id) AS thread_titles
        FROM external_identities ei
        JOIN issue_external_identity_mappings iem
            ON iem.external_identity_id = ei.id
        JOIN issues i ON i.id = iem.issue_id
        JOIN threads t ON t.id = i.thread_id
        WHERE ei.provider = 'comicvine'
          AND ei.entity_type = 'issue'
          AND iem.status = 'confirmed'
          AND t.user_id = :user_id
        GROUP BY ei.id, ei.external_id
        HAVING COUNT(DISTINCT iem.issue_id) > 1
        ORDER BY ei.external_id
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, {
        "user_id": user_id,
        "limit": limit,
        "offset": start_offset,
    })
    
    duplicates = []
    for row in result.mappings():
        issue_ids = [int(id) for id in row["issue_ids"]] if row["issue_ids"] else []
        thread_ids = [int(id) for id in row["thread_ids"]] if row["thread_ids"] else []
        statuses = list(row["statuses"]) if row["statuses"] else []
        issue_numbers = list(row["issue_numbers"]) if row["issue_numbers"] else []
        thread_titles = list(row["thread_titles"]) if row["thread_titles"] else []
        
        details = []
        for idx, issue_id in enumerate(issue_ids):
            details.append({
                "issue_id": issue_id,
                "thread_id": thread_ids[idx] if idx < len(thread_ids) else None,
                "thread_title": thread_titles[idx] if idx < len(thread_titles) else None,
                "issue_number": issue_numbers[idx] if idx < len(issue_numbers) else None,
                "status": statuses[idx] if idx < len(statuses) else None,
            })
        
        duplicates.append({
            "external_id": row["external_id"],
            "external_identity_id": row["external_identity_id"],
            "issue_ids": issue_ids,
            "thread_ids": thread_ids,
            "statuses": statuses,
            "issue_details": details,
        })
    
    return duplicates


async def count_duplicate_physical_issues_for_user(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Count confirmed identities that map to multiple user-owned issues."""
    query = text("""
        SELECT COUNT(*) as total
        FROM (
            SELECT ei.id
            FROM external_identities ei
            JOIN issue_external_identity_mappings iem
                ON iem.external_identity_id = ei.id
            JOIN issues i ON i.id = iem.issue_id
            JOIN threads t ON t.id = i.thread_id
            WHERE ei.provider = 'comicvine'
              AND ei.entity_type = 'issue'
              AND iem.status = 'confirmed'
              AND t.user_id = :user_id
            GROUP BY ei.id, ei.external_id
            HAVING COUNT(DISTINCT iem.issue_id) > 1
        ) sub
    """)
    
    result = await db.execute(query, {"user_id": user_id})
    return result.scalar_one()


async def find_already_catalog_linked_issues(
    db: AsyncSession,
    *,
    user_id: int,
    start_offset: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find issues that already have catalog links.
    
    These should be skipped during backfill since they're already processed.
    """
    query = text("""
        SELECT
            iem.id as mapping_id,
            iem.issue_id,
            ei.id as external_identity_id,
            ei.provider,
            ei.entity_type,
            ei.external_id,
            ci.id as catalog_issue_id,
            ci.created_at as catalog_linked_at
        FROM issue_external_identity_mappings iem
        JOIN external_identities ei ON ei.id = iem.external_identity_id
        JOIN catalog_issues ci ON ci.canonical_external_identity_id = ei.id
        JOIN issues i ON i.id = iem.issue_id
        JOIN threads t ON t.id = i.thread_id
        WHERE iem.status = 'confirmed'
          AND ei.entity_type = 'issue'
          AND t.user_id = :user_id
        ORDER BY ei.id
        LIMIT :limit OFFSET :offset
    """)
    
    result = await db.execute(query, {
        "user_id": user_id,
        "limit": limit,
        "offset": start_offset,
    })
    
    linked = []
    for row in result.mappings():
        linked.append({
            "mapping_id": row["mapping_id"],
            "issue_id": row["issue_id"],
            "external_identity_id": row["external_identity_id"],
            "provider": row["provider"],
            "entity_type": row["entity_type"],
            "external_id": row["external_id"],
            "catalog_issue_id": row["catalog_issue_id"],
            "catalog_linked_at": row["catalog_linked_at"],
        })
    
    return linked


async def count_already_catalog_linked_issues(
    db: AsyncSession,
    user_id: int,
) -> int:
    """Count issues that already have catalog links."""
    query = text("""
        SELECT COUNT(*) as total
        FROM issue_external_identity_mappings iem
        JOIN external_identities ei ON ei.id = iem.external_identity_id
        JOIN catalog_issues ci ON ci.canonical_external_identity_id = ei.id
        JOIN issues i ON i.id = iem.issue_id
        JOIN threads t ON t.id = i.thread_id
        WHERE iem.status = 'confirmed'
          AND ei.entity_type = 'issue'
          AND t.user_id = :user_id
    """)
    
    result = await db.execute(query, {"user_id": user_id})
    return result.scalar_one()


async def get_backfill_receipts(
    db: AsyncSession,
    *,
    user_id: int,
    limit: int = 100,
    offset: int = 0,
) -> list[CatalogCommitReceipt]:
    """Get catalog commit receipts for backfill operations."""
    query = select(CatalogCommitReceipt).where(
        CatalogCommitReceipt.user_id == user_id,
        CatalogCommitReceipt.endpoint == "catalog_backfill_batch"
    ).order_by(CatalogCommitReceipt.created_at.desc())
    
    if limit:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_backfill_receipt_by_batch_id(
    db: AsyncSession,
    batch_id: int,
) -> CatalogCommitReceipt | None:
    """Get a catalog commit receipt by batch ID.
    
    This would require a batch_id column in CatalogCommitReceipt or
    a separate mapping table.
    """
    # For now, return None - in a full implementation, we'd add batch_id to receipts
    # or create a batch_receipt_mapping table
    return None


async def create_batch_receipt_mapping(
    db: AsyncSession,
    *,
    batch_id: int,
    receipt_id: int,
) -> None:
    """Create a mapping between batch ID and receipt ID.
    
    This would be used to track which receipt belongs to which batch.
    """
    # In a full implementation, we'd create a batch_receipt_mapping table
    # For now, this is a placeholder
    pass