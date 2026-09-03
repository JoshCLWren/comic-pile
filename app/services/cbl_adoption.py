"""Read-only preview and adoption-plan services for CBL source lists.

Services provide pure/read-only computation without mutating user-owned reading state.
These services build on the existing reconciliation logic but add series/run grouping
keys and decision application without performing mutations.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSourceList
from app.schemas.cbl_adoption import (
    CBLMutationSummary,
    CBLPreviewResponse,
    CBLSourceEntryPreview,
    CBLSeriesRunGroup,
    CBLSourceMetadata,
    CBLSummaryEntry,
)
from app.services.cbl_reconciliation import (
    CBLReconciliationReport,
    reconcile_cbl_source_list as _reconcile_cbl_source_list,
)


async def preview_cbl_source_list(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
) -> CBLPreviewResponse:
    """Get a read-only preview of one CBL source list for the current user.

    Builds on the existing reconcile_cbl_source_list to add series/run grouping
    keys and provides a structured preview without mutations.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        list_id: CBLSourceList identifier.

    Returns:
        Structured preview response with source metadata, series/run groups,
        and per-entry preview information.

    Raises:
        ValueError: If the source list does not exist or is not active.
    """
    report = await _reconcile_cbl_source_list(db, user_id=user_id, list_id=list_id)

    source = await db.get(CBLSourceList, list_id)
    if source is None or not source.active:
        raise ValueError(f"CBL source list {list_id} not found or not active")

    source_meta = CBLSourceMetadata(
        source_list_id=source.id,
        source_repository=source.repository,
        source_path=source.source_path,
        declared_issue_count=source.declared_issue_count,
        content_hash=source.content_hash,
        revision_sha=source.revision_sha,
    )

    series_run_groups: dict[str, CBLSeriesRunGroup] = {}
    for entry in report.entries:
        group_key = _generate_series_run_group_key(entry)

        group = series_run_groups.get(group_key)
        if not group:
            group = CBLSeriesRunGroup(
                group_key=group_key,
                series_name=entry.get("series_name", ""),
                volume_year=entry.get("volume_year"),
                comicvine_series_id=entry.get("comicvine_series_id"),
                entry_count=0,
            )
            series_run_groups[group_key] = group

        group.entry_count += 1

    grouped_series_runs = list(series_run_groups.values())

    preview_entries: list[CBLSourceEntryPreview] = []
    for entry in report.entries:
        preview_entry = CBLSourceEntryPreview(
            position=entry.get("position", 0),
            series_name=entry.get("series_name", ""),
            issue_number=entry.get("issue_number", ""),
            volume_year=entry.get("volume_year"),
            publication_year=entry.get("publication_year"),
            series_run_group_key=_generate_series_run_group_key(entry),
            comicvine_issue_id=entry.get("comicvine_issue_id"),
            comicvine_series_id=entry.get("comicvine_series_id"),
            state=entry.get("state", "unresolved"),
            read_status=entry.get("read_status"),
            read_at=entry.get("read_at"),
            resolved_issue_id=entry.get("resolved_issue_id"),
            canonical_issue_id=entry.get("canonical_issue_id"),
            resolution_status=entry.get("resolution_status"),
            is_duplicate_identity=entry.get("is_duplicate_identity", False),
        )
        preview_entries.append(preview_entry)

    return CBLPreviewResponse(
        source=source_meta,
        total_positions=report.total_positions,
        entries=preview_entries,
        series_run_groups=grouped_series_runs,
        first_unread_position=report.first_unread_position,
        first_unread_entry_id=report.first_unread_issue_id,
    )


def _generate_series_run_group_key(entry: dict[str, Any]) -> str:
    """Generate a stable series/run grouping key from an entry.

    The key uses comicvine_series_id when available; when the CBL carries no
    ComicVine series evidence, the normalized series name plus volume year
    serve as a stable fallback.
    """
    comicvine_series_id = entry.get("comicvine_series_id")
    if comicvine_series_id:
        return comicvine_series_id

    series_name = entry.get("series_name", "")
    volume_year = entry.get("volume_year")
    if volume_year is not None:
        return f"{series_name}|{volume_year}"

    return series_name


async def calculate_adoption_plan(
    db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    decisions: list[dict[str, Any]],
) -> CBLMutationSummary:
    """Calculate the adoption-plan summary for one CBL source list.

    Applies the proposed decisions to the preview and returns a read-only
    mutation summary without creating or mutating any state. This is a pure
    computation that simulates what would happen without actually performing mutations.

    Args:
        db: Async database session.
        user_id: Owner user ID.
        list_id: CBLSourceList identifier.
        decisions: List of adoption decisions to apply.

    Returns:
        Read-only mutation summary describing what would happen if decisions
        were committed transactionally.

    Raises:
        ValueError: If the source list does not exist or is not active.
    """
    preview = await preview_cbl_source_list(db, user_id=user_id, list_id=list_id)

    existing_issues_reused: list[int] = []
    missing_issues_to_be_created: list[CBLSummaryEntry] = []
    excluded_entries: list[CBLSummaryEntry] = []
    unresolved_skipped_entries: list[CBLSummaryEntry] = []
    adopted_entries: list[CBLSummaryEntry] = []

    for entry in preview.entries:
        entry_state = entry.state
        resolved_issue_id = entry.resolved_issue_id
        canonical_issue_id = entry.canonical_issue_id

        for decision in decisions:
            decision_type = decision.get("decision_type")
            decision_position = decision.get("position")
            decision_series_run_key = decision.get("series_run_group_key")

            should_apply = False
            if decision_position is not None:
                if entry.position == decision_position:
                    should_apply = True
            elif decision_series_run_key is not None:
                if entry.series_run_group_key == decision_series_run_key:
                    should_apply = True

            if not should_apply:
                continue

            if decision_type == "include_entry":
                if resolved_issue_id is not None:
                    existing_issues_reused.append(resolved_issue_id)
                else:
                    missing_issues_to_be_created.append(
                        CBLSummaryEntry(
                            position=entry.position,
                            series_name=entry.series_name,
                            issue_number=entry.issue_number,
                            series_run_group_key=entry.series_run_group_key,
                            comicvine_issue_id=entry.comicvine_issue_id,
                            resolved_issue_id=resolved_issue_id,
                            canonical_issue_id=canonical_issue_id,
                            is_new=resolved_issue_id is None,
                        )
                    )
                adopted_entries.append(
                    CBLSummaryEntry(
                        position=entry.position,
                        series_name=entry.series_name,
                        issue_number=entry.issue_number,
                        series_run_group_key=entry.series_run_group_key,
                        comicvine_issue_id=entry.comicvine_issue_id,
                        resolved_issue_id=resolved_issue_id,
                        canonical_issue_id=canonical_issue_id,
                        is_new=resolved_issue_id is None,
                    )
                )

            elif decision_type == "exclude_entry":
                excluded_entries.append(
                    CBLSummaryEntry(
                        position=entry.position,
                        series_name=entry.series_name,
                        issue_number=entry.issue_number,
                        series_run_group_key=entry.series_run_group_key,
                        comicvine_issue_id=entry.comicvine_issue_id,
                        resolved_issue_id=resolved_issue_id,
                        canonical_issue_id=canonical_issue_id,
                        is_new=resolved_issue_id is None,
                    )
                )

            elif decision_type == "exclude_series":
                excluded_entries.append(
                    CBLSummaryEntry(
                        position=entry.position,
                        series_name=entry.series_name,
                        issue_number=entry.issue_number,
                        series_run_group_key=entry.series_run_group_key,
                        comicvine_issue_id=entry.comicvine_issue_id,
                        resolved_issue_id=resolved_issue_id,
                        canonical_issue_id=canonical_issue_id,
                        is_new=resolved_issue_id is None,
                    )
                )

            elif decision_type == "include_series":
                if resolved_issue_id is not None:
                    existing_issues_reused.append(resolved_issue_id)
                else:
                    missing_issues_to_be_created.append(
                        CBLSummaryEntry(
                            position=entry.position,
                            series_name=entry.series_name,
                            issue_number=entry.issue_number,
                            series_run_group_key=entry.series_run_group_key,
                            comicvine_issue_id=entry.comicvine_issue_id,
                            resolved_issue_id=resolved_issue_id,
                            canonical_issue_id=canonical_issue_id,
                            is_new=resolved_issue_id is None,
                        )
                    )
                adopted_entries.append(
                    CBLSummaryEntry(
                        position=entry.position,
                        series_name=entry.series_name,
                        issue_number=entry.issue_number,
                        series_run_group_key=entry.series_run_group_key,
                        comicvine_issue_id=entry.comicvine_issue_id,
                        resolved_issue_id=resolved_issue_id,
                        canonical_issue_id=canonical_issue_id,
                        is_new=resolved_issue_id is None,
                    )
                )

            elif decision_type == "override_entry":
                if resolved_issue_id is not None:
                    existing_issues_reused.append(resolved_issue_id)
                else:
                    missing_issues_to_be_created.append(
                        CBLSummaryEntry(
                            position=entry.position,
                            series_name=entry.series_name,
                            issue_number=entry.issue_number,
                            series_run_group_key=entry.series_run_group_key,
                            comicvine_issue_id=entry.comicvine_issue_id,
                            resolved_issue_id=resolved_issue_id,
                            canonical_issue_id=canonical_issue_id,
                            is_new=resolved_issue_id is None,
                        )
                    )
                adopted_entries.append(
                    CBLSummaryEntry(
                        position=entry.position,
                        series_name=entry.series_name,
                        issue_number=entry.issue_number,
                        series_run_group_key=entry.series_run_group_key,
                        comicvine_issue_id=entry.comicvine_issue_id,
                        resolved_issue_id=resolved_issue_id,
                        canonical_issue_id=canonical_issue_id,
                        is_new=resolved_issue_id is None,
                    )
                )

    for entry in preview.entries:
        if entry.state not in ["included", "adopted"]:
            unresolved_skipped_entries.append(
                CBLSummaryEntry(
                    position=entry.position,
                    series_name=entry.series_name,
                    issue_number=entry.issue_number,
                    series_run_group_key=entry.series_run_group_key,
                    comicvine_issue_id=entry.comicvine_issue_id,
                    resolved_issue_id=entry.resolved_issue_id,
                    canonical_issue_id=entry.canonical_issue_id,
                    is_new=entry.resolved_issue_id is None,
                )
            )

    adopted_positions = [e.position for e in adopted_entries]

    return CBLMutationSummary(
        source_list_id=list_id,
        total_source_positions=preview.total_positions,
        existing_issues_reused=existing_issues_reused,
        missing_issues_to_be_created=missing_issues_to_be_created,
        excluded_entries=excluded_entries,
        unresolved_skipped_entries=unresolved_skipped_entries,
        adopted_entries=adopted_entries,
        adopted_count=len(adopted_entries),
        final_adopted_order=adopted_positions,
    )
