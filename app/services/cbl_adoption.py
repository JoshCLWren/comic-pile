"""CBL adoption commit service."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.cbl_reference import CBLSourceList, CBLSourceEntry
from app.models.thread import Thread
from app.services.cbl_reconciliation import preview_cbl_adoption
from app.schemas.cbl_adoption import CBLSourceFingerprintResponse
from app.schemas.comicvine_resolution import ImportIssueRequest
from app.services.comicvine_resolution import import_comicvine_issue
from comic_pile.dependencies import refresh_user_blocked_status


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
    source_list = await db.get(CBLSourceList, list_id)
    if source_list is None or not source_list.active:
        raise ValueError(f"CBL source list {list_id} not found or not active")

    from app.models.cbl_reference import CBLSource
    source_result = await db.execute(
        select(CBLSource).where(CBLSource.id == source_list.source_id)
    )
    source = source_result.scalar_one_or_none()
    if source is None:
        raise ValueError(f"Source for CBL source list {list_id} not found")

    if (
        source_list.id != source_fingerprint.source_list_id
        or source.repository != source_fingerprint.source_repository
        or source_list.source_path != source_fingerprint.source_path
        or source_list.content_hash != source_fingerprint.content_hash
        or source_list.revision_sha != source_fingerprint.revision_sha
    ):
        raise StalePreviewError("CBL source has changed since preview")

    report, plan = await preview_cbl_adoption(
        db,
        user_id=user_id,
        list_id=list_id,
        series_decisions=series_decisions,
        entry_decisions=entry_decisions,
    )

    group_name = f"CBL adoption of {source_list.name} ({source.repository}@{source_list.revision_sha[:8]})"

    existing_group_result = await db.execute(
        select(DependencyGroup).where(
            DependencyGroup.user_id == user_id,
            DependencyGroup.name == group_name,
        )
    )
    group = existing_group_result.scalar_one_or_none()
    if group is None:
        group = DependencyGroup(user_id=user_id, name=group_name)
        db.add(group)
        await db.flush()

    await db.execute(
        delete(DependencyGroupMembership).where(
            DependencyGroupMembership.group_id == group.id
        )
    )

    entries_result = await db.execute(
        select(CBLSourceEntry)
        .where(CBLSourceEntry.list_id == list_id)
        .order_by(CBLSourceEntry.position)
    )
    source_entries = entries_result.scalars().all()

    plan_by_position: dict[int, dict[str, Any]] = {
        int(cast(int, entry["cbl_position"])): cast(dict[str, Any], entry)
        for entry in plan.entries
    }

    reused_issue_ids: list[int] = []
    created_issue_ids: list[int] = []
    created_thread_ids: list[int] = []
    excluded_positions: list[int] = []
    unresolved_positions: list[int] = []
    membership_ids: list[int] = []
    sequence_positions: list[int] = []
    reused_details: list[dict[str, Any]] = []
    created_issues: list[dict[str, Any]] = []

    for entry in source_entries:
        position = entry.position
        plan_entry = plan_by_position.get(position)
        if plan_entry is None:
            continue

        decision = plan_entry.get("adoption_decision")

        if decision in ("excluded", "awaiting_opt_in"):
            if decision == "excluded":
                excluded_positions.append(position)
            continue

        if decision == "unresolved":
            unresolved_positions.append(position)
            continue

        if decision == "included_existing":
            issue_id = cast(int | None, plan_entry.get("resolved_issue_id"))
            if issue_id is None:
                continue
            reused_issue_ids.append(issue_id)
            issue = await db.get(Issue, issue_id)
            assert issue is not None
            reused_details.append({
                "issue_id": issue.id,
                "read_status": issue.status,
                "read_at": issue.read_at,
            })
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
            comicvine_id = plan_entry.get("comicvine_issue_id")
            if comicvine_id is None:
                continue
            import_request = ImportIssueRequest(
                title=f"{entry.series_name} #{entry.issue_number}",
                issue_number=str(entry.issue_number),
                comicvine_issue_id=int(comicvine_id),
                reading_order_id=None,
                anchor_before_thread_id=None,
                anchor_after_thread_id=None,
            )
            import_result = await import_comicvine_issue(
                db,
                user_id=user_id,
                request=import_request,
            )
            created_thread_ids.append(import_result.thread_id)
            created_issue_ids.append(import_result.issue_id)
            issue_id = import_result.issue_id
            thread = await db.get(Thread, import_result.thread_id)
            issue = await db.get(Issue, import_result.issue_id)
            assert thread is not None
            assert issue is not None
            created_issues.append({
                "issue_id": issue.id,
                "thread_id": thread.id,
                "read_status": issue.status,
                "read_at": issue.read_at,
            })
            membership = DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue.id,
                sequence_order=position,
            )
            db.add(membership)
            await db.flush()
            membership_ids.append(membership.id)
            sequence_positions.append(position)
        else:
            continue

    await db.commit()

    await refresh_user_blocked_status(user_id, db)

    return {
        "reused_issue_ids": reused_issue_ids,
        "created_issue_ids": created_issue_ids,
        "created_thread_ids": created_thread_ids,
        "excluded_positions": excluded_positions,
        "unresolved_positions": unresolved_positions,
        "membership_ids": membership_ids,
        "sequence_positions": sequence_positions,
        "blocker_refreshed": True,
        "reused_details": reused_details,
        "created_issues": created_issues,
    }
