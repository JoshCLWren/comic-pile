"""Build the reader-facing Reading Plan progress and availability view.

Availability uses the guarded live evaluator when enabled. Disabled readers keep
the transitional issue-level Dependency authority. Neither mode compiles list
adjacency or treats ContinuityRule rows as execution authority.
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from comic_pile.dependencies import build_blocking_explanation
from app.repositories import continuity_repository, reading_plan_repository
from app.services import reading_plan_release_source_service as release_source_service
from app.services.reading_eligibility_service import (
    get_execution_eligibility, project_blocking_explanation,
)
from app.services.reading_plan_normalization import get_plan_progress
from app.repositories.reading_plan_repository import (
    CanonicalIncomingBlocker,
    ReadingPlanIssueIdentity,
)
from app.schemas.reading_plan_membership import (
    ReadingPlanProgress,
    ReadingPlanSourceSnapshot,
)
from app.schemas.reading_plan_reader import (
    ReadingPlanBlocker,
    ReadingPlanIssueAvailability,
    ReadingPlanReaderIssue,
    ReadingPlanReaderLane,
    ReadingPlanReaderResponse,
)


def _lane_catalog(lanes_json: list[dict[str, object]]) -> list[tuple[str, str, int]]:
    """Return ordered ``(lane_id, name, order)`` tuples from persisted lanes.

    Args:
        lanes_json: Plan ``lanes_json`` payload.

    Returns:
        Lane catalog in declared order, falling back to insertion order.
    """
    catalog: list[tuple[str, str, int]] = []
    for index, lane in enumerate(lanes_json):
        lane_id = lane.get("id")
        if not isinstance(lane_id, str) or not lane_id:
            continue
        raw_name = lane.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name.strip() else lane_id
        raw_order = lane.get("order")
        order = raw_order if isinstance(raw_order, int) else index
        catalog.append((lane_id, name, order))
    catalog.sort(key=lambda item: (item[2], item[0]))
    return catalog


def _availability_for(
    identity: ReadingPlanIssueIdentity,
    blockers: list[ReadingPlanBlocker],
) -> ReadingPlanIssueAvailability:
    """Classify one occurrence against Roll's next-unread + Dependency rule.

    Args:
        identity: Joined plan occurrence.
        blockers: Unsatisfied canonical incoming Dependencies.

    Returns:
        Reader availability for this occurrence.
    """
    if identity.issue_status == "read":
        return "read"
    if identity.thread_next_unread_issue_id != identity.issue_id:
        return "later"
    if blockers:
        return "blocked"
    return "available"


def _blockers_for(
    identity: ReadingPlanIssueIdentity,
    incoming: dict[int, list[CanonicalIncomingBlocker]],
) -> list[ReadingPlanBlocker]:
    """Project unread canonical incoming edges onto reader blocker rows.

    Args:
        identity: Joined plan occurrence.
        incoming: Incoming unread Dependency sources keyed by target Issue.

    Returns:
        Deduplicated blocker rows in first-seen order.
    """
    if identity.issue_status == "read":
        return []
    seen: set[int] = set()
    blockers: list[ReadingPlanBlocker] = []
    for row in incoming.get(identity.issue_id, []):
        if row.source_issue_id in seen:
            continue
        seen.add(row.source_issue_id)
        blockers.append(
            ReadingPlanBlocker(
                issue_id=row.source_issue_id,
                thread_id=row.source_thread_id,
                thread_title=row.source_thread_title,
                issue_number=row.source_issue_number,
                explanation=build_blocking_explanation(
                    row.source_issue_number,
                    row.source_thread_title,
                ),
            )
        )
    return blockers


def _source_paths_for(
    occurrence_id: str,
    placements: list[tuple[str, str]],
) -> list[str]:
    """Return distinct source paths observed for one occurrence.

    Args:
        occurrence_id: Plan occurrence id.
        placements: ``(occurrence_id, raw_source_path)`` pairs.

    Returns:
        Distinct source paths in first-seen order.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for placed_occurrence, raw_path in placements:
        if placed_occurrence != occurrence_id or raw_path in seen:
            continue
        seen.add(raw_path)
        paths.append(raw_path)
    return paths


def _to_reader_issue(
    identity: ReadingPlanIssueIdentity,
    incoming: dict[int, list[CanonicalIncomingBlocker]],
    placements: list[tuple[str, str]],
) -> ReadingPlanReaderIssue:
    """Build one reader issue row from identity, blockers, and provenance.

    Args:
        identity: Joined plan occurrence.
        incoming: Incoming unread Dependency sources keyed by target Issue.
        placements: ``(occurrence_id, raw_source_path)`` pairs.

    Returns:
        Reader-facing issue row.
    """
    blockers = _blockers_for(identity, incoming)
    return ReadingPlanReaderIssue(
        occurrence_id=identity.occurrence_id,
        issue_id=identity.issue_id,
        lane_id=identity.lane_id,
        display_position=identity.display_position,
        label=identity.label,
        reader_role=identity.reader_role,
        reader_optional=identity.reader_optional,
        is_checkpoint=identity.is_checkpoint,
        issue_number=identity.issue_number,
        thread_id=identity.thread_id,
        thread_title=identity.thread_title,
        status=identity.issue_status,
        availability=_availability_for(identity, blockers),
        blockers=blockers,
        source_paths=_source_paths_for(identity.occurrence_id, placements),
    )


async def get_reading_plan_reader(
    db: AsyncSession,
    *,
    user_id: int,
    plan_id: int,
) -> ReadingPlanReaderResponse:
    """Return the primary reader view for one owned Reading Plan.

    Args:
        db: Database session.
        user_id: Authenticated plan owner.
        plan_id: Plan to inspect.

    Raises:
        HTTPException: 404 when the plan is not owned.

    Returns:
        Progress, available-now, blocked-next, lanes, and source provenance.
    """
    plan = await continuity_repository.get_continuity_plan(
        db, user_id=user_id, plan_id=plan_id
    )
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Continuity plan {plan_id} not found")
    plan_id_value = plan.id
    plan_name = plan.name
    ordering_mode = plan.ordering_mode
    lanes_json = plan.lanes_json
    identities = await reading_plan_repository.list_plan_issue_identities(
        db, plan_id=plan_id_value
    )
    eligibility = await get_execution_eligibility(db, user_id)
    incoming_rows = (await reading_plan_repository.list_canonical_incoming_blockers(
        db, user_id=user_id, issue_ids=[row.issue_id for row in identities]
    )) if eligibility is None else []
    incoming: dict[int, list[CanonicalIncomingBlocker]] = defaultdict(list)
    for row in incoming_rows:
        incoming[row.target_issue_id].append(row)
    sources = await reading_plan_repository.list_plan_sources(db, plan_id=plan_id_value)
    source_paths_by_id = {source.id: source.raw_source_path for source in sources}
    placement_rows = await reading_plan_repository.list_plan_source_placements(
        db, plan_id=plan_id_value
    )
    placements = [
        (placement.occurrence_id, source_paths_by_id[placement.plan_source_id])
        for placement in placement_rows
        if placement.plan_source_id in source_paths_by_id
    ]
    reader_issues = [_to_reader_issue(identity, incoming, placements) for identity in identities]
    if eligibility is not None:
        for issue in reader_issues:
            issue.blockers = []
            if issue.status == "read":
                issue.availability = "read"
                continue
            state = eligibility.threads.get(issue.thread_id)
            if issue.issue_id in eligibility.excluded_issue_ids:
                issue.availability = "excluded"
            elif state is None:
                issue.availability = "inactive"
            elif state.next_issue_id != issue.issue_id:
                issue.availability = "later"
            else:
                issue.availability = "available" if state.eligible else "blocked"
                explanation = project_blocking_explanation(eligibility, issue.thread_id)
                issue.blockers = [ReadingPlanBlocker(
                    issue_id=dependency.issue_id,
                    thread_id=dependency.thread_id,
                    thread_title=dependency.thread_title,
                    issue_number=dependency.issue_number,
                    explanation=dependency.label,
                ) for dependency in explanation.blocking_dependencies
                    if dependency.issue_id is not None]
    available_now = [issue for issue in reader_issues if issue.availability == "available"]
    blocked_next = [issue for issue in reader_issues if issue.availability == "blocked"]
    issues_by_lane: dict[str, list[ReadingPlanReaderIssue]] = defaultdict(list)
    for issue in reader_issues:
        issues_by_lane[issue.lane_id].append(issue)
    lane_catalog = _lane_catalog(lanes_json)
    seen_lane_ids = {lane_id for lane_id, _, _ in lane_catalog}
    for lane_id in issues_by_lane:
        if lane_id not in seen_lane_ids:
            lane_catalog.append((lane_id, lane_id, len(lane_catalog)))
            seen_lane_ids.add(lane_id)
    total_issues, read_issues = await get_plan_progress(db, plan_id=plan_id_value)
    release_sources = await release_source_service.list_release_sources_for_reader(
        db, plan_id=plan_id_value, user_id=user_id
    )
    return ReadingPlanReaderResponse(
        execution_mode="option_e" if eligibility is not None else "legacy",
        plan_id=plan_id_value,
        name=plan_name,
        ordering_mode=ordering_mode,
        progress=ReadingPlanProgress(
            total_issues=total_issues,
            read_issues=read_issues,
        ),
        available_now=available_now,
        blocked_next=blocked_next,
        lanes=[
            ReadingPlanReaderLane(
                id=lane_id,
                name=lane_name,
                order=lane_order,
                issues=issues_by_lane.get(lane_id, []),
            )
            for lane_id, lane_name, lane_order in lane_catalog
        ],
        sources=[
            ReadingPlanSourceSnapshot(
                id=source.id,
                raw_source_path=source.raw_source_path,
                repository=source.repository,
                source_path=source.source_path,
                revision_sha=source.revision_sha,
                content_hash=source.content_hash,
                adopted_at=source.adopted_at,
                recorded_at=source.recorded_at,
            )
            for source in sources
        ],
        release_sources=release_sources,
    )
