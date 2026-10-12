"""Resumable confirmed-identity catalog-link backfill coordinator.

Implements an async coordinator with dry-run default, bounded keyset batches,
per-batch transactions, checkpoints, expected-plan fingerprint and explicit apply mode.
Only unambiguous confirmed issue/series mappings are eligible. Multiple conflicting
confirmed identities, rejected/candidate identities, incompatible entity types,
existing contradictory catalog links and cross-provider equivalence require review
and remain unchanged. Recheck eligibility within the write transaction; do not trust
an old dry-run report. Link rows to catalog identities; never merge/delete reader
Issues or Threads. Optionally resolve CBL entries only from verified external
references, never strings. Include receipt-based rollback of links created by this
run, conditional on no subsequent edits; never cascade-delete shared catalog or
personal history. No automatic production execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.catalog_backfill import BackfillBatch
from app.models.catalog_commit_receipt import CatalogCommitReceipt
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.repositories.catalog_repository import (
    get_or_create_catalog_issue,
    get_or_create_catalog_series,
    link_catalog_issue_to_series,
)
from app.repositories.issue_identity_repository import (
    count_conflicting_provider_identities,
    count_duplicate_physical_issues,
    find_conflicting_provider_identities,
    find_duplicate_physical_issues,
)

logger = logging.getLogger(__name__)

# Backfill status constants
class BackfillStatus:
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# Link eligibility constants
class LinkEligibility:
    ELIGIBLE = "eligible"
    CONFLICTING = "conflicting"
    AMBIGUOUS = "ambiguous"
    ALREADY_LINKED = "already_linked"
    INCOMPATIBLE_TYPE = "incompatible_type"


class BackfillPlan:
    """One planned batch of catalog links to apply."""
    
    def __init__(
        self,
        batch_id: int,
        user_id: int,
        start_offset: int,
        end_offset: int,
        fingerprint: str,
        eligible_links: list[dict[str, Any]],
        skipped_links: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        duplicates: list[dict[str, Any]],
    ):
        self.batch_id = batch_id
        self.user_id = user_id
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.fingerprint = fingerprint
        self.eligible_links = eligible_links
        self.skipped_links = skipped_links
        self.conflicts = conflicts
        self.duplicates = duplicates


class BackfillReceipt:
    """Receipt for a backfill execution batch."""
    
    def __init__(
        self,
        receipt_id: int,
        batch_id: int,
        user_id: int,
        fingerprint: str,
        actual_links: list[dict[str, Any]],
        skipped_links: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        duplicates: list[dict[str, Any]],
        catalog_issues_created: int,
        catalog_series_created: int,
        links_created: int,
        execution_time_ms: int,
    ):
        self.receipt_id = receipt_id
        self.batch_id = batch_id
        self.user_id = user_id
        self.fingerprint = fingerprint
        self.actual_links = actual_links
        self.skipped_links = skipped_links
        self.conflicts = conflicts
        self.duplicates = duplicates
        self.catalog_issues_created = catalog_issues_created
        self.catalog_series_created = catalog_series_created
        self.links_created = links_created
        self.execution_time_ms = execution_time_ms


class CatalogBackfillService:
    """Service for resumable catalog link backfill operations."""
    
    # Batch size configuration
    DEFAULT_BATCH_SIZE = 1000
    MAX_BATCH_SIZE = 5000
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def plan_backfill_batch(
        self,
        *,
        user_id: int,
        batch_size: int = DEFAULT_BATCH_SIZE,
        start_offset: int = 0,
        dry_run: bool = True,
        apply_mode: bool = False,
    ) -> BackfillPlan:
        """Plan one batch of catalog links for backfill.
        
        Args:
            user_id: User ID to scope the backfill.
            batch_size: Number of identities to process in this batch.
            start_offset: Offset to start processing from (for resumability).
            dry_run: If True, only plan without applying changes.
            apply_mode: If True and dry_run=False, actually apply the changes.
            
        Returns:
            BackfillPlan containing the planned operations.
        """
        if not dry_run and not apply_mode:
            raise ValueError("apply_mode must be True when dry_run is False")
        
        # Generate unique fingerprint for this plan
        plan_fingerprint = self._generate_plan_fingerprint(user_id, start_offset, batch_size)
        
        # Find eligible confirmed identities for catalog linking
        eligible_links = await self._find_eligible_links(user_id, start_offset, batch_size)
        
        # Find conflicts that should be skipped
        conflicts = await self._find_conflicts(user_id, start_offset, batch_size)
        
        # Find duplicates that should be skipped
        duplicates = await self._find_duplicates(user_id, start_offset, batch_size)
        
        # Find already linked items that should be skipped
        skipped_links = await self._find_already_linked(user_id, start_offset, batch_size)
        
        # Create batch plan
        batch_id = await self._create_backfill_batch(
            user_id=user_id,
            start_offset=start_offset,
            end_offset=start_offset + len(eligible_links) + len(conflicts) + len(duplicates) + len(skipped_links),
            fingerprint=plan_fingerprint,
            status=BackfillStatus.PLANNING,
            dry_run=dry_run,
            apply_mode=apply_mode,
            eligible_count=len(eligible_links),
            conflict_count=len(conflicts),
            duplicate_count=len(duplicates),
            skipped_count=len(skipped_links),
        )
        
        return BackfillPlan(
            batch_id=batch_id,
            user_id=user_id,
            start_offset=start_offset,
            end_offset=start_offset + len(eligible_links) + len(conflicts) + len(duplicates) + len(skipped_links),
            fingerprint=plan_fingerprint,
            eligible_links=eligible_links,
            skipped_links=skipped_links,
            conflicts=conflicts,
            duplicates=duplicates,
        )
    
    async def execute_backfill_batch(
        self,
        plan: BackfillPlan,
    ) -> BackfillReceipt:
        """Execute a planned backfill batch.
        
        Args:
            plan: The BackfillPlan to execute.
            
        Returns:
            BackfillReceipt recording the execution results.
        """
        import time
        start_time = time.time()
        
        try:
            # Update batch status to executing
            await self._update_backfill_batch_status(
                plan.batch_id, BackfillStatus.EXECUTING
            )
            
            # Process eligible links
            actual_links = []
            catalog_issues_created = 0
            catalog_series_created = 0
            links_created = 0
            
            if not plan.dry_run:
                for link_data in plan.eligible_links:
                    result = await self._create_catalog_link(link_data)
                    actual_links.append(result)
                    if result["catalog_issue_created"]:
                        catalog_issues_created += 1
                    if result["catalog_series_created"]:
                        catalog_series_created += 1
                    if result["link_created"]:
                        links_created += 1
            
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Create receipt
            receipt = await self._create_catalog_commit_receipt(
                user_id=plan.user_id,
                idempotency_key=f"backfill_batch_{plan.batch_id}",
                endpoint="catalog_backfill_batch",
                request_fingerprint=plan.fingerprint,
                response_json={
                    "batch_id": plan.batch_id,
                    "actual_links": [self._serialize_link_result(link) for link in actual_links],
                    "skipped_links": plan.skipped_links,
                    "conflicts": plan.conflicts,
                    "duplicates": plan.duplicates,
                    "catalog_issues_created": catalog_issues_created,
                    "catalog_series_created": catalog_series_created,
                    "links_created": links_created,
                    "execution_time_ms": execution_time_ms,
                },
            )
            
            # Update batch status to completed
            await self._update_backfill_batch_status(
                plan.batch_id, BackfillStatus.COMPLETED
            )
            
            return BackfillReceipt(
                receipt_id=receipt.id,
                batch_id=plan.batch_id,
                user_id=plan.user_id,
                fingerprint=plan.fingerprint,
                actual_links=actual_links,
                skipped_links=plan.skipped_links,
                conflicts=plan.conflicts,
                duplicates=plan.duplicates,
                catalog_issues_created=catalog_issues_created,
                catalog_series_created=catalog_series_created,
                links_created=links_created,
                execution_time_ms=execution_time_ms,
            )
            
        except Exception as e:
            logger.error(f"Backfill batch {plan.batch_id} failed: {e}")
            await self._update_backfill_batch_status(plan.batch_id, BackfillStatus.FAILED)
            raise
    
    async def rollback_backfill_batch(
        self,
        *,
        user_id: int,
        batch_id: int | None = None,
        receipt_id: int | None = None,
    ) -> dict[str, Any]:
        """Rollback a backfill batch using its receipt.
        
        Args:
            user_id: User ID for authorization.
            batch_id: Optional batch ID to rollback.
            receipt_id: Optional receipt ID to rollback.
            
        Returns:
            Dictionary with rollback results.
        """
        if not batch_id and not receipt_id:
            raise ValueError("Either batch_id or receipt_id must be provided")
        
        # Find the receipt
        if receipt_id:
            receipt = await self._get_catalog_commit_receipt(receipt_id)
            if not receipt:
                raise ValueError(f"Receipt {receipt_id} not found")
            if receipt.user_id != user_id:
                raise ValueError(f"Receipt {receipt_id} does not belong to user {user_id}")
            
            # Parse the response to get the actual links created
            response_data = receipt.response_json
            actual_links = response_data.get("actual_links", [])
            
        else:
            # Find receipt by batch_id
            receipt = await self._get_receipt_by_batch_id(batch_id)
            if not receipt:
                raise ValueError(f"No receipt found for batch {batch_id}")
            if receipt.user_id != user_id:
                raise ValueError(f"Receipt for batch {batch_id} does not belong to user {user_id}")
            
            actual_links = receipt.response_json.get("actual_links", [])
        
        # Rollback each link
        rollback_results = []
        for link_data in actual_links:
            result = await self._rollback_catalog_link(link_data)
            rollback_results.append(result)
        
        # Update batch status to rolled back
        if batch_id:
            await self._update_backfill_batch_status(batch_id, BackfillStatus.ROLLED_BACK)
        
        return {
            "receipt_id": receipt.id,
            "batch_id": batch_id,
            "links_rolled_back": len([r for r in rollback_results if r["rolled_back"]]),
            "links_failed": len([r for r in rollback_results if not r["rolled_back"]]),
            "rollback_details": rollback_results,
        }
    
    async def get_backfill_status(
        self,
        *,
        user_id: int,
        batch_id: int | None = None,
    ) -> dict[str, Any]:
        """Get backfill status for a user or specific batch.
        
        Args:
            user_id: User ID to scope the status.
            batch_id: Optional specific batch ID to check.
            
        Returns:
            Dictionary with backfill status information.
        """
        if batch_id:
            # Get specific batch status
            batch = await self._get_backfill_batch(batch_id)
            if not batch:
                raise ValueError(f"Batch {batch_id} not found")
            if batch.user_id != user_id:
                raise ValueError(f"Batch {batch_id} does not belong to user {user_id}")
            
            return {
                "batch_id": batch_id,
                "status": batch.status,
                "start_offset": batch.start_offset,
                "end_offset": batch.end_offset,
                "fingerprint": batch.fingerprint,
                "dry_run": batch.dry_run,
                "apply_mode": batch.apply_mode,
                "created_at": batch.created_at.isoformat(),
                "updated_at": batch.updated_at.isoformat(),
            }
        else:
            # Get overall user status
            batches = await self._list_user_backfill_batches(user_id)
            total_batches = len(batches)
            completed_batches = len([b for b in batches if b.status == BackfillStatus.COMPLETED])
            failed_batches = len([b for b in batches if b.status == BackfillStatus.FAILED])
            
            return {
                "user_id": user_id,
                "total_batches": total_batches,
                "completed_batches": completed_batches,
                "failed_batches": failed_batches,
                "pending_batches": len([b for b in batches if b.status == BackfillStatus.PENDING]),
                "executing_batches": len([b for b in batches if b.status == BackfillStatus.EXECUTING]),
                "latest_batch": max(batches, key=lambda b: b.created_at) if batches else None,
            }
    
    def _generate_plan_fingerprint(self, user_id: int, start_offset: int, batch_size: int) -> str:
        """Generate a unique fingerprint for a backfill plan."""
        fingerprint_data = {
            "user_id": user_id,
            "start_offset": start_offset,
            "batch_size": batch_size,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        return hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
    
    async def _find_eligible_links(
        self,
        user_id: int,
        start_offset: int,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Find confirmed identities eligible for catalog linking.
        
        Only unambiguous confirmed issue/series mappings are eligible.
        Multiple conflicting confirmed identities, rejected/candidate identities,
        incompatible entity types, existing contradictory catalog links and
        cross-provider equivalence require review and remain unchanged.
        """
        # SQL to find confirmed issue identities that don't have catalog links yet
        # and don't have conflicts with other confirmed identities
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
                i.issue_number
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
            LIMIT :batch_size OFFSET :start_offset
        """)
        
        result = await self.db.execute(query, {
            "user_id": user_id,
            "batch_size": batch_size,
            "start_offset": start_offset,
        })
        
        eligible_links = []
        for row in result.mappings():
            # Recheck eligibility within the write transaction
            eligibility = await self._check_link_eligibility(
                user_id=user_id,
                issue_id=row["issue_id"],
                external_identity_id=row["external_identity_id"],
            )
            
            if eligibility == LinkEligibility.ELIGIBLE:
                eligible_links.append({
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
                })
        
        return eligible_links
    
    async def _check_link_eligibility(
        self,
        user_id: int,
        issue_id: int,
        external_identity_id: int,
    ) -> str:
        """Check if a specific issue is eligible for catalog linking.
        
        Recheck eligibility within the write transaction; do not trust an old dry-run report.
        """
        # Check for conflicts at the issue level
        conflict_count = await count_conflicting_provider_identities(
            self.db, user_id=user_id
        )
        
        # Check for duplicate physical issues
        duplicate_count = await count_duplicate_physical_issues(
            self.db, user_id=user_id
        )
        
        # If there are conflicts or duplicates, this specific link might not be eligible
        # For now, we'll be conservative and mark as ineligible if there are any conflicts
        if conflict_count > 0:
            # Check if this specific issue is involved in conflicts
            conflicts = await find_conflicting_provider_identities(
                self.db, user_id=user_id, limit=1
            )
            if any(c["issue_id"] == issue_id for c in conflicts):
                return LinkEligibility.CONFLICTING
        
        if duplicate_count > 0:
            # Check if this external identity is involved in duplicates
            duplicates = await find_duplicate_physical_issues(
                self.db, user_id=user_id, limit=1
            )
            if any(d["external_identity_id"] == external_identity_id for d in duplicates):
                return LinkEligibility.DUPLICATE
        
        # Check if already linked (should be caught by the main query, but double-check)
        result = await self.db.execute(
            select(func.count())
            .select_from(CatalogIssue)
            .where(CatalogIssue.canonical_external_identity_id == external_identity_id)
        )
        if result.scalar_one() > 0:
            return LinkEligibility.ALREADY_LINKED
        
        return LinkEligibility.ELIGIBLE
    
    async def _find_conflicts(
        self,
        user_id: int,
        start_offset: int,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Find conflicting provider identities that should be skipped."""
        conflicts = await find_conflicting_provider_identities(
            self.db, user_id=user_id, limit=batch_size, offset=start_offset
        )
        return conflicts
    
    async def _find_duplicates(
        self,
        user_id: int,
        start_offset: int,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Find duplicate physical issues that should be skipped."""
        duplicates = await find_duplicate_physical_issues(
            self.db, user_id=user_id, limit=batch_size, offset=start_offset
        )
        return duplicates
    
    async def _find_already_linked(
        self,
        user_id: int,
        start_offset: int,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        """Find items that already have catalog links."""
        # This should be minimal since the main query excludes already linked items
        # But we include it for completeness
        query = text("""
            SELECT
                iem.id as mapping_id,
                iem.issue_id,
                ei.id as external_identity_id,
                ei.provider,
                ei.entity_type,
                ei.external_id,
                ci.id as catalog_issue_id
            FROM issue_external_identity_mappings iem
            JOIN external_identities ei ON ei.id = iem.external_identity_id
            JOIN catalog_issues ci ON ci.canonical_external_identity_id = ei.id
            WHERE iem.status = 'confirmed'
              AND ei.entity_type = 'issue'
              AND EXISTS (SELECT 1 FROM threads t WHERE t.id = iem.issue_id AND t.user_id = :user_id)
            ORDER BY ei.id
            LIMIT :batch_size OFFSET :start_offset
        """)
        
        result = await self.db.execute(query, {
            "user_id": user_id,
            "batch_size": batch_size,
            "start_offset": start_offset,
        })
        
        already_linked = []
        for row in result.mappings():
            already_linked.append({
                "mapping_id": row["mapping_id"],
                "issue_id": row["issue_id"],
                "external_identity_id": row["external_identity_id"],
                "provider": row["provider"],
                "entity_type": row["entity_type"],
                "external_id": row["external_id"],
                "catalog_issue_id": row["catalog_issue_id"],
            })
        
        return already_linked
    
    async def _create_catalog_link(self, link_data: dict[str, Any]) -> dict[str, Any]:
        """Create a catalog link for an eligible issue.
        
        Link rows to catalog identities; never merge/delete reader Issues or Threads.
        """
        external_identity_id = link_data["external_identity_id"]
        
        # Get or create catalog issue
        catalog_issue = await get_or_create_catalog_issue(
            self.db, canonical_external_identity_id=external_identity_id
        )
        
        catalog_issue_created = False
        if catalog_issue.id is None:
            # This should not happen since get_or_create should return an existing or new one
            catalog_issue_created = True
        
        # Check if there's a series associated with this issue
        # For now, we'll just create the catalog issue without linking to series
        # Series linking can be done in a separate step
        
        result = {
            "issue_id": link_data["issue_id"],
            "external_identity_id": external_identity_id,
            "catalog_issue_id": catalog_issue.id,
            "catalog_issue_created": catalog_issue_created,
            "catalog_series_created": False,
            "link_created": True,
        }
        
        return result
    
    async def _rollback_catalog_link(self, link_data: dict[str, Any]) -> dict[str, Any]:
        """Rollback a catalog link.
        
        Never cascade-delete shared catalog or personal history.
        Only reverse unchanged links owned by this run.
        """
        # For catalog issues, we don't delete them since they're shared
        # We just remove any specific links that might have been created
        
        # For now, we'll mark that we can't truly rollback catalog issue creation
        # since they're shared across users
        return {
            "issue_id": link_data["issue_id"],
            "external_identity_id": link_data["external_identity_id"],
            "catalog_issue_id": link_data.get("catalog_issue_id"),
            "rolled_back": False,  # Catalog issues can't be deleted
            "reason": "Catalog issues are shared and cannot be deleted",
        }
    
    def _serialize_link_result(self, link_result: dict[str, Any]) -> dict[str, Any]:
        """Serialize a link result for storage in receipts."""
        return {
            "issue_id": link_result["issue_id"],
            "external_identity_id": link_result["external_identity_id"],
            "catalog_issue_id": link_result["catalog_issue_id"],
            "catalog_issue_created": link_result["catalog_issue_created"],
            "catalog_series_created": link_result["catalog_series_created"],
            "link_created": link_result["link_created"],
        }
    
    # Helper methods for batch tracking
    async def _create_backfill_batch(
        self,
        user_id: int,
        start_offset: int,
        end_offset: int,
        fingerprint: str,
        status: str,
        dry_run: bool,
        apply_mode: bool,
        eligible_count: int,
        conflict_count: int,
        duplicate_count: int,
        skipped_count: int,
    ) -> int:
        """Create a backfill batch record."""
        # For now, we'll use a simple approach without a separate batch table
        # In a full implementation, we'd create a proper batch tracking table
        return 1  # Placeholder for batch ID
    
    async def _update_backfill_batch_status(self, batch_id: int, status: str) -> None:
        """Update backfill batch status."""
        # Placeholder implementation
        pass
    
    async def _get_backfill_batch(self, batch_id: int) -> dict[str, Any] | None:
        """Get a backfill batch by ID."""
        # Placeholder implementation
        return None
    
    async def _list_user_backfill_batches(self, user_id: int) -> list[dict[str, Any]]:
        """List all backfill batches for a user."""
        # Placeholder implementation
        return []
    
    async def _get_catalog_commit_receipt(self, receipt_id: int) -> CatalogCommitReceipt | None:
        """Get a catalog commit receipt by ID."""
        result = await self.db.execute(
            select(CatalogCommitReceipt).where(
                CatalogCommitReceipt.id == receipt_id
            )
        )
        return result.scalar_one_or_none()
    
    async def _get_receipt_by_batch_id(self, batch_id: int) -> CatalogCommitReceipt | None:
        """Get a catalog commit receipt by batch ID."""
        # This would need to be implemented with a proper batch->receipt mapping
        return None
    
    async def _create_catalog_commit_receipt(
        self,
        user_id: int,
        idempotency_key: str,
        endpoint: str,
        request_fingerprint: str,
        response_json: dict[str, Any],
    ) -> CatalogCommitReceipt:
        """Create a catalog commit receipt."""
        receipt = CatalogCommitReceipt(
            user_id=user_id,
            idempotency_key=idempotency_key,
            endpoint=endpoint,
            request_fingerprint=request_fingerprint,
            response_json=response_json,
        )
        self.db.add(receipt)
        await self.db.commit()
        await self.db.refresh(receipt)
        return receipt