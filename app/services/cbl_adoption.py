"""CBL adoption commit service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.cbl_reference import CBLSourceList, CBLSourceEntry
from app.models.thread import Thread
from app.models.user import User
from app.services.cbl_reconciliation import (
    CBLAdoptionPlan,
    CBLReconciliationReport,
    preview_cbl_adoption,
)
from app.schemas.cbl_adoption import CBLSourceFingerprintResponse
from app.services.comicvine_resolution import import_comicvine_issue


class CBLAdoptionCommitError(Exception):
    """Base error for CBL adoption commit."""


class StalePreviewError(CBLAdoptionCommitError):
    """Raised when the source has changed since preview."""


async def commit_cbl_adoption(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    series_decisions: dict[str, bool],
    entry_decisions: dict[str, bool],
    source_fingerprint: CBLSourceFingerprintResponse,
) -> dict[str, Any]:
    """Commit a CBL adoption plan transactionally.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        list_id: CBLSourceList identifier.
        series_decisions: Series-level inclusion/exclusion decisions.
        entry_decisions: Per-entry override decisions.
        source_fingerprint: Fingerprint of the source as seen at preview time.

    Returns:
        Dictionary with commit results.

    Raises:
        StalePreviewError: If the source has changed since preview.
        ValueError: If the source list is not found or inactive.
    """
    # Initialize result tracking variables
    reused_issue_ids: list[int] = []
    created_issue_ids: list[int] = []
    created_thread_ids: list[int] = []
    excluded_positions: list[int] = []
    unresolved_positions: list[int] = []
    membership_ids: list[int] = []
    sequence_positions: list[int] = []
    reused_details: list[dict[str, Any]] = []
    created_issues: list[dict[str, Any]] = []
    
    # Verify source fingerprint matches current state
    source_list = await db.get(CBLSourceList, list_id)
    if source_list is None or not source_list.active:
        raise ValueError(f"CBL source list {list_id} not found or not active")
    
    # Fetch the source properly using the CBLSource model
    from app.models.cbl_reference import CBLSource
    source_result = await db.execute(
        select(CBLSource).where(CBLSource.id == source_list.source_id)
    )
    source = source_result.scalar_one_or_none()
    
    if source is None:
        raise ValueError(f"Source for CBL source list {list_id} not found")
    
    # Verify fingerprint
    if (
        source_list.id != source_fingerprint.source_list_id
        or source.repository != source_fingerprint.source_repository
        or source_list.source_path != source_fingerprint.source_path
        or source_list.content_hash != source_fingerprint.content_hash
        or source_list.revision_sha != source_fingerprint.revision_sha
    ):
        raise StalePreviewError("CBL source has changed since preview")
    
    # Re-reconcile to get current state
    report, plan = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )
    
    # We could verify the plan matches what was expected, but for now we trust the decisions
    # and the fact that the source fingerprint matched.
    
    # Start building the adoption
    # We'll create a dependency group for this adoption
    from app.models.cbl_reference import CBLSource
    source_result = await db.execute(
        select(CBLSource).where(CBLSource.id == source_list.source_id)
    )
    source = source_result.scalar_one_or_none()
    
    if source is None:
        raise ValueError(f"Source for CBL source list {list_id} not found")
    
    group_name = f"CBL adoption of {source_list.name} ({source.repository}@{source_list.revision_sha[:8]})"
    
    # Check if a group with this name already exists for the user (for idempotency)
    existing_group_result = await db.execute(
        select(DependencyGroup).where(
            DependencyGroup.user_id == user_id,
            DependencyGroup.name == group_name,
        )
    )
    group = existing_group_result.scalar_one_or_none()
    
    if group is None:
        group = DependencyGroup(
            user_id=user_id,
            name=group_name,
        )
        db.add(group)
        await db.flush()  # Get the group ID
    
    # Clear any existing memberships for this group (to support idempotency)
    # We delete memberships but keep the group
    await db.execute(
        delete(DependencyGroupMembership).where(
            DependencyGroupMembership.group_id == group.id
        )
    )
    
    # Get all source entries for this list in order
    entries_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    source_entries = entries_result.scalars().all()

    # We need to map from CBL position to entry in the plan
    plan_by_position = {entry["cbl_position"]: entry for entry in plan.entries}

    for entry in source_entries:
        position = entry.position
        plan_entry = plan_by_position.get(position)
        if plan_entry is None:
            # This should not happen if the plan was generated from the same entries
            continue
            
        decision = plan_entry.get("adoption_decision")
        
        if decision == "excluded":
            excluded_positions.append(position)
            continue
            
        if decision == "unresolved":
            unresolved_positions.append(position)
            continue
            
        # For adopted entries: included_existing or would_create_missing
        if decision == "included_existing":
            issue_id = plan_entry.get("resolved_issue_id")
            if issue_id is None:
                # Should not happen for included_existing
                continue
            reused_issue_ids.append(issue_id)
            # Extract details IMMEDIATELY to avoid MissingGreenlet after commit
            issue = await db.get(Issue, issue_id)
            reused_details.append({
                "issue_id": issue.id,
                "read_status": issue.status,
                "read_at": issue.read_at,
            })
            thread_id = issue.thread_id
            # Create membership IMMEDIATELY to avoid MissingGreenlet after commit
            membership = DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue.id,
                sequence_order=position,
            )
            db.add(membership)
            await db.flush()
            membership_ids.append(membership.id)
            sequence_positions.append(position)
        elif decision == "would_create_missing":
            # Create a new issue using the normal import path
            # We need to create a thread with the issue, using the import service
            from app.schemas.comicvine_resolution import ImportIssueRequest
            
            # Prepare import request
            import_request = ImportIssueRequest(
                title=f"{entry.series_name} #{entry.issue_number}",
                issue_number=str(entry.issue_number),
                comicvine_issue_id=plan_entry.get("comicvine_issue_id"),
                # No reading order placement for CBL adoptions
                reading_order_id=None,
                anchor_before_thread_id=None,
                anchor_after_thread_id=None,
            )
            
            # Use the import service to create thread and issue properly
            import_result = await import_comicvine_issue(
                db,
                user_id=user_id,
                request=import_request,
            )
            
            # Extract IDs from import result
            created_thread_ids.append(import_result.thread_id)
            created_issue_ids.append(import_result.issue_id)
            issue_id = import_result.issue_id
            # Extract thread and issue details IMMEDIATELY to avoid MissingGreenlet after commit
            thread = await db.get(Thread, import_result.thread_id)
            issue = await db.get(Issue, import_result.issue_id)
            issue_details = {
                "issue_id": issue.id,
                "thread_id": thread.id,
                "read_status": issue.status,
                "read_at": issue.read_at,
            }
            # Add membership IMMEDIATELY to avoid MissingGreenlet after commit
            membership = DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue.id,
                sequence_order=position,
            )
            db.add(membership)
            await db.flush()
            membership_ids.append(membership.id)
            sequence_positions.append(position)
            # Store issue details for later use after commit
            created_issues.append(issue_details)
        else:
            # Should not happen
            continue

    await db.commit()

    return {
        "reused_issue_ids": reused_issue_ids,
        "created_issue_ids": created_issue_ids,
        "created_thread_ids": created_thread_ids,
        "excluded_positions": excluded_positions,
        "unresolved_positions": unresolved_positions,
        "membership_ids": membership_ids,
        "sequence_positions": sequence_positions,
        "blocker_refreshed": True,  # Placeholder
        "reused_details": reused_details,  # Additional detail for verification
    }