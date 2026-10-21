"""Roll business logic and orchestration.

Services own business rules, transaction boundaries (commit/rollback),
and cache invalidation. Query construction lives in
``app.repositories.roll_repository``. HTTP status mapping lives in routers.
"""

import logging
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypedDict

# Import comic_pile first to resolve circular dependency with
# comic_pile.bandwidth -> app.services.reading_effort.
from fastapi import HTTPException, status
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Thread, User
from app.models.thread import normalize_format_value
from app.models.recommendation_context import RecommendationContext as RecContextModel
from app.repositories.roll_repository import (
    count_blocked_exclusion_rows,
    count_inactive_exclusion_rows,
    fetch_blocked_exclusion_page,
    fetch_bootstrap_blocked_rows,
    fetch_bootstrap_excluded_thread_rows,
    fetch_bootstrap_library_rows,
    fetch_bootstrap_pool_rows,
    fetch_bootstrap_stale_rows,
    fetch_inactive_exclusion_page,
    fetch_issue_by_id,
    fetch_latest_session_event,
    fetch_pending_thread_id,
    fetch_thread_by_id,
    insert_event,
    fetch_session_events,
    insert_recommendation_context,
    update_session_pending_thread,
    update_session_skipped,
)
from app.services.dependency_service import get_blocking_details
from app.services.queue_display import display_position
from app.services.reading_effort import (
    EffortEstimate,
    build_recommendation_context,
    compute_effort_estimate,
)
from app.services.reading_eligibility_service import (
    get_execution_eligibility, project_blocking_explanation,
)
from app.services.bandwidth_selection import select_bandwidth_weighted
from app.services.snooze_service import (
    derive_effective_roll_excluded_thread_ids,
    derive_cross_session_excluded_thread_ids,
)
from app.services.explanation_projection import get_primary_explanation
from app.schemas.recommendation_context import (
    CandidateFactor,
    RecommendationContextCreate,
)
from app.momentum import MomentumCandidateWeight
from comic_pile.recommendation_selection import (
    DEFAULT_BANDWIDTH,
    DEFAULT_INTENT,
    SelectionMode,
    normalize_bandwidth,
    normalize_intent,
    resolve_selection_mode,
    select_from_pool,
)
from comic_pile.recommendation_version import (
    CONTROL_MODE_CONTEXTUAL,
    FORCED_LEGACY_REASON_CODE,
    FORCED_LEGACY_SELECTION_METHOD,
    RECOMMENDATION_ALGORITHM_VERSION,
    recommendation_algorithm_version,
)
from comic_pile.reading_session import (
    get_current_die_for_session,
    get_or_create,
    resolve_current_session,
)

from app.config import get_recommendation_settings
from app.schemas import RollBootstrapThread, RollResponse, ThreadExclusionReason

logger = logging.getLogger(__name__)


class _SelectionArtifacts(TypedDict):
    """Bundle of selection artifacts returned by ``select_pending_thread``.

    The shared selection logic builds a plain dict so the router can wrap it
    in its own ``_SelectionArtifacts`` without duplicating fields. TypedDict
    lets callers access each artifact with a precise type instead of ``object``.
    """

    selected_thread: Thread
    unread_count: int
    issue_number: str | None
    selected_thread_issue_id: int | None
    selected_thread_issue_number: str | None
    bounded_rows: list[tuple[Thread, int, str | None]]
    selected_index: int
    bounded_candidate_ids: list[int]
    candidate_weights: list
    selected_effort_estimate: EffortEstimate
    json_candidate_weights: list[dict[str, object]] | None
    json_selected_weight: float | None
    recommendation_context: dict[str, object]
    recommendation_reason_codes: list[str]
    selection_method: str
    event: Event
    rec_context_create: RecommendationContextCreate


@dataclass(frozen=True)
class BootstrapLibrarySummary:
    """Exclusion-transparency classification of a user's whole library.

    Every owned series is either available or excluded, and every exclusion
    carries a reason the user can read, so the response totals always add up.
    """

    total_threads: int
    available_ids: set[int]
    excluded: dict[int, ThreadExclusionReason]
    inactive: list[ThreadExclusionReason]
    blocked_ids: list[int]


@dataclass(frozen=True)
class ExclusionPage:
    """One deterministic page of a Roll exclusion category (issue #3330).

    The Roll bootstrap carries bounded previews, so the page heading needs the
    category total while the expanded section loads rows on demand. ``total``
    and ``items`` are produced from the same predicate, so a drill-down page can
    never contradict the bootstrap count it belongs to.
    """

    category: Literal["blocked", "inactive"]
    items: list[ThreadExclusionReason]
    total: int


@dataclass(frozen=True)
class BootstrapThreadData:
    """Thread-shaped sections of the Roll bootstrap payload."""

    roll_pool: list[RollBootstrapThread]
    snoozed_threads: list[RollBootstrapThread]
    skipped_threads: list[RollBootstrapThread]
    blocked_threads: list[RollBootstrapThread]
    blocked_count: int
    stale_thread: RollBootstrapThread | None
    stale_thread_count: int
    library: BootstrapLibrarySummary


def _summary_thread(row: Row[Any]) -> RollBootstrapThread:
    """Build the id/title/format summary shared by every summary list.

    Args:
        row: Row carrying ``id``, ``title``, and ``format``.

    Returns:
        Minimal thread summary for the bootstrap response.
    """
    return RollBootstrapThread(
        id=row.id,
        title=row.title,
        format=normalize_format_value(row.format),
        last_activity_at=(
            row.last_activity_at.isoformat() if getattr(row, "last_activity_at", None) else None
        ),
    )


def _classify_library(
    library_rows: Sequence[Row[Any]],
    *,
    snoozed_set: set[int],
    derived_snoozed_ids: set[int],
    skipped_set: set[int],
) -> BootstrapLibrarySummary:
    """Split the owned library into available series and explained exclusions.

    Availability mirrors the roll pool's own predicates: queued, unblocked,
    and not snoozed or skipped in any scope. A rollable series beyond the die
    window is still available, so a series is never reported as excluded just
    because the pool query is capped.

    Args:
        library_rows: Active and completed rows for the owner.
        snoozed_set: Thread IDs snoozed in the current session.
        derived_snoozed_ids: Thread IDs excluded by cross-session backoff.
        skipped_set: Thread IDs skipped in the current session.

    Returns:
        BootstrapLibrarySummary with totals, availability, and exclusions.
    """
    available_ids: set[int] = set()
    excluded: dict[int, ThreadExclusionReason] = {}
    inactive: list[ThreadExclusionReason] = []
    blocked_ids: list[int] = []

    for row in library_rows:
        thread_id = row.id
        if row.status == "completed":
            # Completed series sit outside the active status and never reach
            # the pool query, so they vanish silently unless explained here.
            reason = ThreadExclusionReason(
                thread_id=thread_id,
                title=row.title,
                format=normalize_format_value(row.format),
                reason="completed",
                detail="Read the full series",
            )
            excluded[thread_id] = reason
            inactive.append(reason)
            continue

        is_blocked = bool(row.is_blocked)
        is_rollable = (
            row.queue_position >= 1
            and not is_blocked
            and thread_id not in snoozed_set
            and thread_id not in derived_snoozed_ids
            and thread_id not in skipped_set
        )
        if is_rollable:
            available_ids.add(thread_id)
            continue

        if is_blocked:
            blocked_ids.append(thread_id)
            reason_value: Literal["blocked", "snoozed", "skipped", "not_in_queue"] = "blocked"
            detail = None
        elif thread_id in snoozed_set:
            reason_value = "snoozed"
            detail = "Snoozed in current session"
        elif thread_id in derived_snoozed_ids:
            reason_value = "snoozed"
            detail = "Snoozed by cross-session backoff"
        elif thread_id in skipped_set:
            reason_value = "skipped"
            detail = "Skipped in current session"
        else:
            reason_value = "not_in_queue"
            detail = "Not in the active queue"

        reason = ThreadExclusionReason(
            thread_id=thread_id,
            title=row.title,
            format=normalize_format_value(row.format),
            reason=reason_value,
            detail=detail,
        )
        excluded[thread_id] = reason
        # Snoozed, skipped, and blocked series keep their own dedicated Roll
        # sections, so only series that vanished from the queue entirely are
        # reported as inactive alongside completed ones.
        if reason_value == "not_in_queue":
            inactive.append(reason)

    return BootstrapLibrarySummary(
        total_threads=len(library_rows),
        available_ids=available_ids,
        excluded=excluded,
        inactive=inactive,
        blocked_ids=blocked_ids,
    )


class RollService:
    """Service for roll orchestration.

    Owns the core roll selection, commit, and response-building logic
    previously embedded in ``app.api.roll``.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the RollService with a database session."""
        self._db = db

    async def load_bootstrap_thread_data(
        self,
        *,
        user_id: int,
        die_size: int,
        snoozed_ids: list[int],
        skipped_ids: list[int],
        derived_snoozed_ids: set[int],
        summary_limit: int,
        include_pool: bool = True,
    ) -> BootstrapThreadData:
        """Load every thread-shaped section of the Roll bootstrap payload.

        Issue #3375 recorded this endpoint at 1962 ms against a 1000 ms
        budget with 36 database queries, because each response section asked
        the ``threads`` table its own question: the pool, the snoozed list,
        the skipped list, the blocked count, the blocked rows, the stale
        count, the stale candidates, the chosen stale row, the active library,
        and the completed library. Every one of those reads hits the same
        owner-scoped rows, so this method answers them with a fixed set of
        batched reads whose count does not depend on the library size:
        windowed counts replace the separate ``COUNT`` statements, and the
        snoozed, skipped, active, and completed sets are each read once.

        Args:
            user_id: Authenticated owner of the library.
            die_size: Current die size bounding the roll pool.
            snoozed_ids: Thread IDs snoozed in the current session.
            skipped_ids: Thread IDs skipped in the current session.
            derived_snoozed_ids: Thread IDs excluded by cross-session backoff.
            summary_limit: Maximum rows kept per summary list in the response.
            include_pool: False when a v2 projection has already loaded candidates.

        Returns:
            BootstrapThreadData with the pool, summary lists, stale pick, and
            the exclusion-transparency library classification.
        """
        eligibility = await get_execution_eligibility(self._db, user_id)
        eligibility_args = {"eligibility": eligibility} if eligibility is not None else {}
        effective_snoozed_ids = sorted(set(snoozed_ids) | set(derived_snoozed_ids))
        pool_excluded_ids = sorted(set(effective_snoozed_ids) | set(skipped_ids))

        pool_rows = (
            (
                await fetch_bootstrap_pool_rows(
                    self._db, user_id, die_size, pool_excluded_ids, **eligibility_args
                )
            )
            if include_pool
            else []
        )
        roll_pool = [
            RollBootstrapThread(
                id=row.id,
                title=row.title,
                format=normalize_format_value(row.format),
                issue_id=(
                    eligibility.threads[row.id].next_issue_id
                    if eligibility is not None
                    else row.issue_id
                ),
                issue_number=(
                    eligibility.issue_numbers.get(eligibility.threads[row.id].next_issue_id)
                    if eligibility is not None
                    else row.issue_number
                ),
                route_labels=list(row.route_labels or []),
            )
            for row in pool_rows
        ]

        excluded_rows = await fetch_bootstrap_excluded_thread_rows(
            self._db, user_id, sorted(set(snoozed_ids) | set(skipped_ids))
        )
        snoozed_set = set(snoozed_ids)
        skipped_set = set(skipped_ids)
        snoozed_threads = [
            _summary_thread(row) for row in excluded_rows if row.id in snoozed_set
        ]
        skipped_threads = [
            _summary_thread(row) for row in excluded_rows if row.id in skipped_set
        ]

        blocked_rows = await fetch_bootstrap_blocked_rows(
            self._db, user_id, summary_limit, **eligibility_args
        )
        blocked_threads = [_summary_thread(row) for row in blocked_rows]
        if eligibility is not None:
            for thread in blocked_threads:
                thread.blocking_reasons = project_blocking_explanation(
                    eligibility, thread.id,
                ).blocking_reasons
        blocked_count = blocked_rows[0].blocked_total if blocked_rows else 0

        stale_cutoff = datetime.now(UTC) - timedelta(days=7)
        stale_excluded_ids = pool_excluded_ids if eligibility is not None else effective_snoozed_ids
        stale_rows = await fetch_bootstrap_stale_rows(
            self._db, user_id, stale_cutoff, stale_excluded_ids, **eligibility_args
        )
        stale_thread_count = stale_rows[0].stale_total if stale_rows else 0
        stale_thread = None
        if stale_rows:
            # Pick by ID so the choice stays a uniform draw over candidates,
            # then look the winner up instead of re-reading it from the DB.
            stale_by_id = {row.id: row for row in stale_rows}
            chosen = stale_by_id[random.choice(list(stale_by_id))]
            stale_thread = RollBootstrapThread(
                id=chosen.id,
                title=chosen.title,
                format=normalize_format_value(chosen.format),
                last_activity_at=(
                    chosen.last_activity_at.isoformat() if chosen.last_activity_at else None
                ),
            )

        library_rows = await fetch_bootstrap_library_rows(self._db, user_id, **eligibility_args)
        library = _classify_library(
            library_rows,
            snoozed_set=snoozed_set,
            derived_snoozed_ids=derived_snoozed_ids,
            skipped_set=skipped_set,
        )

        return BootstrapThreadData(
            roll_pool=roll_pool,
            snoozed_threads=snoozed_threads,
            skipped_threads=skipped_threads,
            blocked_threads=blocked_threads,
            blocked_count=blocked_count,
            stale_thread=stale_thread,
            stale_thread_count=stale_thread_count,
            library=library,
        )

    async def load_exclusion_page(
        self,
        *,
        user_id: int,
        category: Literal["blocked", "inactive"],
        limit: int,
        offset: int,
    ) -> ExclusionPage:
        """Load one deterministic page of a Roll exclusion category.

        Issue #3330: the Roll bootstrap intentionally carries bounded previews,
        but the collapsed headings must report the real category totals and the
        expanded section must reach every counted series. This method answers
        both with the same predicate set used by the bootstrap classification,
        so the count beside a section always equals the number of rows the
        drill-down exposes.

        Args:
            user_id: Authenticated owner of the library.
            category: ``blocked`` (waiting on an earlier issue) or ``inactive``
                (completed or otherwise out of the active queue).
            limit: Maximum rows in this page.
            offset: Rows to skip in the deterministic category order.

        Returns:
            ExclusionPage with the page rows and the authoritative category total.
        """
        eligibility = await get_execution_eligibility(self._db, user_id)
        eligibility_args = {"eligibility": eligibility} if eligibility is not None else {}

        if category == "blocked":
            total = await count_blocked_exclusion_rows(
                self._db, user_id, **eligibility_args
            )
            rows = await fetch_blocked_exclusion_page(
                self._db, user_id, limit=limit, offset=offset, **eligibility_args
            )
            blocking_map = await get_blocking_details(
                [row.id for row in rows], user_id, self._db
            )
            items: list[ThreadExclusionReason] = []
            for row in rows:
                explanation = blocking_map.get(row.id)
                reasons = explanation.blocking_reasons if explanation is not None else []
                dependencies = (
                    explanation.blocking_dependencies if explanation is not None else []
                )
                items.append(
                    ThreadExclusionReason(
                        thread_id=row.id,
                        title=row.title,
                        format=normalize_format_value(row.format),
                        reason="blocked",
                        detail=reasons[0] if reasons else None,
                        blocking_reasons=reasons,
                        blocking_dependencies=dependencies,
                        last_activity_at=(
                            row.last_activity_at.isoformat()
                            if row.last_activity_at is not None
                            else None
                        ),
                    )
                )
            return ExclusionPage(category=category, items=items, total=total)

        # The drill-down must classify rows exactly like the bootstrap did, so it
        # resolves the same current reading session the bootstrap resolves
        # (`get_or_create` prefers a recent session that still has pending
        # reading work over the newest unended one). Reading the newest
        # unended session instead could disagree with the bootstrap about
        # which series are skipped or snoozed, and a series the bootstrap
        # classified as skipped would then appear here as inactive (#3330).
        session = await resolve_current_session(self._db, user_id)
        snoozed_ids = set(session.snoozed_thread_ids or []) if session is not None else set()
        skipped_ids = set(session.skipped_thread_ids or []) if session is not None else set()
        # The bootstrap derives cross-session backoff exclusions whether or not a
        # session row exists, so the drill-down derives them the same way.
        derived_snoozed_ids = await derive_cross_session_excluded_thread_ids(self._db, user_id)
        session_excluded_ids = sorted(snoozed_ids | derived_snoozed_ids | skipped_ids)

        total = await count_inactive_exclusion_rows(
            self._db,
            user_id,
            session_excluded_ids=session_excluded_ids,
            **eligibility_args,
        )
        rows = await fetch_inactive_exclusion_page(
            self._db,
            user_id,
            limit=limit,
            offset=offset,
            session_excluded_ids=session_excluded_ids,
            **eligibility_args,
        )
        inactive_items = [
            ThreadExclusionReason(
                thread_id=row.id,
                title=row.title,
                format=normalize_format_value(row.format),
                reason="completed" if row.status == "completed" else "not_in_queue",
                detail=(
                    "Read the full series"
                    if row.status == "completed"
                    else "Not in the active queue"
                ),
                last_activity_at=(
                    row.last_activity_at.isoformat()
                    if row.last_activity_at is not None
                    else None
                ),
            )
            for row in rows
        ]
        return ExclusionPage(category=category, items=inactive_items, total=total)

    async def select_pending_thread(
        self,
        *,
        user_id: int,
        current_session: ReadingSession,
        current_die: int,
        excluded_ids: list[int],
        selection_bandwidth: str,
        selection_intent: str,
        selection_method_override: str | None = None,
        empty_pool_detail: str = "No active threads available to roll",
    ) -> _SelectionArtifacts:
        """Run the weighted bounded-pool selection shared by roll and skip.

        Returns a dictionary of selection artifacts without committing.

        Raises:
            HTTPException: 400 when the bounded pool is empty.
        """
        from comic_pile.queue import get_bounded_roll_pool_rows

        eligibility = await get_execution_eligibility(self._db, user_id)
        bounded_rows = await get_bounded_roll_pool_rows(
            user_id, self._db, current_die, excluded_ids,
        )
        if not bounded_rows:
            raise HTTPException(status_code=400, detail=empty_pool_detail)

        recommendation_settings = get_recommendation_settings()
        control_mode = recommendation_settings.control_mode
        algorithm_version = recommendation_algorithm_version(control_mode)

        pool_size = len(bounded_rows)
        resolved_mode = resolve_selection_mode(
            selection_bandwidth, selection_intent, control_mode
        )

        weights_applied = False
        candidate_weights: list = []
        if resolved_mode is SelectionMode.FORCED_LEGACY:
            selection = select_from_pool(
                pool_size,
                bandwidth=selection_bandwidth,
                intent=selection_intent,
                control_mode=control_mode,
            )
            selected_index = selection.index
            candidate_weights = [
                MomentumCandidateWeight(
                    candidate_id=row[0].id if isinstance(row, tuple) else row.id,
                    weight=1.0,
                    factors=(),
                )
                for row in bounded_rows
            ]
        elif resolved_mode is SelectionMode.PURE_RANDOM_BYPASS:
            selection = select_from_pool(
                pool_size,
                bandwidth=selection_bandwidth,
                intent=selection_intent,
            )
            selected_index = selection.index
            candidate_weights = [
                MomentumCandidateWeight(
                    candidate_id=row[0].id if isinstance(row, tuple) else row.id,
                    weight=1.0,
                    factors=(),
                )
                for row in bounded_rows
            ]
        else:
            session_events = await fetch_session_events(self._db, current_session.id)
            selected = await select_bandwidth_weighted(
                db=self._db,
                bounded_rows=bounded_rows,
                user_id=user_id,
                session_events=session_events,
                bandwidth=selection_bandwidth,
                intent=selection_intent,
                now=datetime.now(UTC),
            )
            selected_index = selected.selected_index
            candidate_weights = selected.weights
            weights_applied = selected.weights_applied

        if resolved_mode is SelectionMode.FORCED_LEGACY:
            recommendation_reason_codes = [FORCED_LEGACY_REASON_CODE]
        elif resolved_mode is not SelectionMode.PURE_RANDOM_BYPASS and weights_applied:
            if selection_bandwidth in ("light", "deep"):
                recommendation_reason_codes = ["bandwidth_weighted"]
            else:
                recommendation_reason_codes = ["momentum_weighted"]
        else:
            recommendation_reason_codes = ["pure_random"]

        selected_thread, unread_count, issue_number = bounded_rows[selected_index]
        bounded_candidate_ids = [
            row[0].id if isinstance(row, tuple) else row.id for row in bounded_rows
        ]

        selected_thread_issue_id = None
        selected_thread_issue_number = None
        selected_frontier = (
            eligibility.threads[selected_thread.id].next_issue_id
            if eligibility is not None
            else selected_thread.next_unread_issue_id
        )
        if eligibility is not None:
            selected_thread_issue_id = selected_frontier
            selected_thread_issue_number = eligibility.issue_numbers.get(selected_frontier)
        elif selected_frontier is not None and selected_thread.uses_issue_tracking():
            if unread_count > 0 and issue_number is not None:
                selected_thread_issue_id = selected_frontier
                selected_thread_issue_number = issue_number
            else:
                issue = await fetch_issue_by_id(self._db, selected_frontier)
                if issue and issue.status == "unread":
                    selected_thread_issue_id = issue.id
                    selected_thread_issue_number = issue.issue_number

        effort_estimates: list[EffortEstimate] = []
        for thread, _unread_count, _issue_number in bounded_rows:
            issue_id = (
                eligibility.threads[thread.id].next_issue_id
                if eligibility is not None
                else thread.next_unread_issue_id
                if thread.uses_issue_tracking()
                else None
            )
            effort_estimate = await compute_effort_estimate(
                self._db,
                user_id=user_id,
                thread_id=thread.id,
                issue_id=issue_id,
            )
            effort_estimates.append(effort_estimate)
        selected_effort_estimate = effort_estimates[selected_index]

        json_candidate_weights: list[dict[str, object]] | None = None
        json_selected_weight: float | None = None
        if candidate_weights:
            json_candidate_weights = [
                {
                    "candidate_id": entry.candidate_id,
                    "weight": round(float(entry.weight), 4),
                    "reasons": list(entry.factors),
                    "factors": list(entry.factors),
                }
                for entry in candidate_weights
            ]
            json_selected_weight = float(candidate_weights[selected_index].weight)

        recommendation_context = build_recommendation_context(
            selected_effort_estimate,
            thread_id=selected_thread.id,
            issue_id=selected_thread_issue_id,
            issue_number=selected_thread_issue_number,
            candidate_weights=json_candidate_weights,
            bandwidth=normalize_bandwidth(selection_bandwidth).value,
            bandwidth_source=current_session.bandwidth_source or "default",
            bandwidth_confidence=current_session.bandwidth_confidence or 0.0,
            random_bypass=not weights_applied,
            balanced_neutrality=not weights_applied,
            selected_weight=json_selected_weight,
            algorithm_version=algorithm_version,
            control_mode=control_mode,
        )

        if selection_method_override is not None:
            selection_method = selection_method_override
        elif resolved_mode is SelectionMode.FORCED_LEGACY:
            selection_method = FORCED_LEGACY_SELECTION_METHOD
        elif resolved_mode is not SelectionMode.PURE_RANDOM_BYPASS and weights_applied:
            selection_method = "bandwidth" if selection_bandwidth in ("light", "deep") else "momentum"
        else:
            selection_method = "random"

        effort_estimate_str = (
            selected_effort_estimate.band
            if isinstance(selected_effort_estimate, EffortEstimate)
            else selected_effort_estimate
        )

        event = Event(
            type="roll",
            session_id=current_session.id,
            selected_thread_id=selected_thread.id,
            die=current_die,
            result=selected_index + 1,
            selection_method=selection_method,
            recommendation_reason_codes=recommendation_reason_codes,
            recommendation_context=recommendation_context,
            issue_id=selected_thread_issue_id,
            issue_number=selected_thread_issue_number,
            rolling_recommendation_context=self._build_rolling_recommendation_context(
                die_size=current_die,
                selected_queue_position=selected_thread.queue_position,
                bounded_candidate_ids=bounded_candidate_ids,
                selected_index=selected_index,
                selection_method=selection_method,
                session_timezone=current_session.timezone,
                selected_thread_last_rating=selected_thread.last_rating,
                selected_thread_last_activity_at=selected_thread.last_activity_at,
                effort_estimate=effort_estimate_str,
                algorithm_version=algorithm_version,
                control_mode=control_mode,
            ),
        )

        rec_context_create = RecommendationContextCreate(
            schema_version=2,
            intent=normalize_intent(selection_intent).value,
            intent_source=current_session.intent_source or "default",
            intent_confidence=1.0 if current_session.active_intent else 0.0,
            bandwidth=normalize_bandwidth(selection_bandwidth).value,
            bandwidth_source=current_session.bandwidth_source or "default",
            bandwidth_confidence=current_session.bandwidth_confidence or 0.0,
            candidate_factors=[
                CandidateFactor(
                    candidate_id=breakdown.candidate_id,
                    factors=list(breakdown.factors),
                    weight=breakdown.weight,
                    effort_minutes=(
                        round(effort_estimate.minutes, 2)
                        if effort_estimate.minutes is not None
                        else None
                    ),
                    effort_band=effort_estimate.band,
                    effort_source=effort_estimate.source.value,
                    effort_confidence=round(effort_estimate.confidence, 3),
                    effort_sample_count=effort_estimate.sample_count,
                )
                for breakdown, effort_estimate in zip(candidate_weights, effort_estimates, strict=True)
            ]
            if candidate_weights
            else None,
            final_weight=(
                candidate_weights[selected_index].weight if candidate_weights else None
            ),
            random_bypass=not weights_applied,
            balanced_neutrality=not weights_applied,
            effort_minutes=(
                round(selected_effort_estimate.minutes, 2)
                if selected_effort_estimate.minutes is not None
                else None
            ),
            effort_band=selected_effort_estimate.band,
            effort_source=selected_effort_estimate.source.value,
            effort_confidence=round(selected_effort_estimate.confidence, 3),
            effort_sample_count=selected_effort_estimate.sample_count,
        )

        return {
            "selected_thread": selected_thread,
            "unread_count": unread_count,
            "issue_number": issue_number,
            "selected_thread_issue_id": selected_thread_issue_id,
            "selected_thread_issue_number": selected_thread_issue_number,
            "bounded_rows": bounded_rows,
            "selected_index": selected_index,
            "bounded_candidate_ids": bounded_candidate_ids,
            "candidate_weights": candidate_weights,
            "selected_effort_estimate": selected_effort_estimate,
            "json_candidate_weights": json_candidate_weights,
            "json_selected_weight": json_selected_weight,
            "recommendation_context": recommendation_context,
            "recommendation_reason_codes": recommendation_reason_codes,
            "selection_method": selection_method,
            "event": event,
            "rec_context_create": rec_context_create,
        }

    def _build_rolling_recommendation_context(
        self,
        *,
        die_size: int,
        selected_queue_position: int,
        bounded_candidate_ids: list[int],
        selected_index: int,
        selection_method: str,
        session_timezone: str | None,
        selected_thread_last_rating: float | None,
        selected_thread_last_activity_at: datetime | None,
        effort_estimate: str | None = None,
        algorithm_version: str | None = None,
        control_mode: str | None = None,
    ) -> dict[str, object]:
        """Build the rolling recommendation context snapshot for a roll event."""
        local_hour = self._get_local_hour_from_timezone(session_timezone)
        return {
            "schema_version": 1,
            "algorithm_version": algorithm_version or RECOMMENDATION_ALGORITHM_VERSION,
            "control_mode": control_mode or CONTROL_MODE_CONTEXTUAL,
            "die_size": die_size,
            "selected_queue_position": selected_queue_position,
            "bounded_candidate_ids": bounded_candidate_ids,
            "selected_index": selected_index,
            "selection_method": selection_method,
            "session_timezone": session_timezone,
            "local_hour": local_hour,
            "selected_thread_last_rating": selected_thread_last_rating,
            "selected_thread_last_activity_at": selected_thread_last_activity_at.isoformat()
            if selected_thread_last_activity_at else None,
            "effort_estimate": effort_estimate,
        }

    def _get_local_hour_from_timezone(self, timezone: str | None) -> int | None:
        """Derive local hour from session timezone."""
        if timezone is None:
            return None
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(timezone)).hour
        except Exception:
            return None

    async def build_roll_response(
        self,
        *,
        selected_thread: Thread | None = None,
        thread_attrs: dict | None = None,
        current_die: int,
        selected_index: int,
        unread_count: int,
        snoozed_count: int,
        issue_id: int | None = None,
        issue_number: str | None = None,
        next_issue_id: int | None = None,
        next_issue_number: str | None = None,
        recommendation_reason_codes: list[str] | None = None,
    ) -> RollResponse:
        """Convert selection artifacts into the public RollResponse.

        Either ``selected_thread`` or ``thread_attrs`` must be provided. The
        displayed Queue ordinal is resolved here, in the service layer, so the
        router never performs the whole-queue lookup itself. Optional issue
        fields and reason codes let callers surface the selected issue and its
        reader-facing explanation while keeping response assembly in the
        service.

        Args:
            selected_thread: ORM thread selected by the roll.
            thread_attrs: Pre-extracted thread attributes (alternative to
                ``selected_thread``).
            current_die: Current die size at roll time.
            selected_index: Zero-based index of the selected candidate.
            unread_count: Remaining unread issue count.
            snoozed_count: Number of snoozed series for the offset.
            issue_id: Selected issue ID, when issue tracking applies.
            issue_number: Selected issue number, when issue tracking applies.
            next_issue_id: Next unread issue ID, mirrored to the client.
            next_issue_number: Next unread issue number, mirrored to the client.
            recommendation_reason_codes: Decision-time reason codes projected
                into the reader-facing explanation.

        Returns:
            A fully populated ``RollResponse``.
        """
        if thread_attrs is not None:
            thread_id = thread_attrs["thread_id"]
            title = thread_attrs["title"]
            format_ = normalize_format_value(thread_attrs["format"]) if isinstance(thread_attrs.get("format"), str) else normalize_format_value(thread_attrs["format"]) if thread_attrs.get("format") else None
            queue_position = thread_attrs["queue_position"]
            total_issues = thread_attrs["total_issues"]
            reading_progress = thread_attrs["reading_progress"]
        else:
            if selected_thread is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Selected thread not found",
                )
            thread_id = selected_thread.id
            title = selected_thread.title
            format_ = normalize_format_value(selected_thread.format)
            queue_position = await display_position(self._db, selected_thread)
            total_issues = selected_thread.total_issues
            reading_progress = selected_thread.reading_progress
        return RollResponse(
            thread_id=thread_id,
            title=title,
            format=format_,
            issues_remaining=unread_count,
            queue_position=queue_position,
            die_size=current_die,
            result=selected_index + 1,
            offset=snoozed_count,
            snoozed_count=snoozed_count,
            issue_id=issue_id,
            issue_number=issue_number,
            next_issue_id=next_issue_id,
            next_issue_number=next_issue_number,
            total_issues=total_issues,
            reading_progress=reading_progress,
            explanation=get_primary_explanation(recommendation_reason_codes),
        )

    async def execute_dismiss_pending(self, current_user_id: int) -> None:
        """Execute the dismiss_pending_roll flow."""
        current_session = await get_or_create(self._db, user_id=current_user_id, existing_user=None)
        now = datetime.now(UTC)
        
        # Record the dismiss action as an event for history tracking
        pending_thread_id = current_session.pending_thread_id
        if pending_thread_id is not None:
            dismiss_event = Event(
                type="dismiss",
                session_id=current_session.id,
                timestamp=now,
                selected_thread_id=pending_thread_id,
                selection_method="cancel",
            )
            self._db.add(dismiss_event)
        
        from app.repositories.roll_repository import clear_session_pending
        await clear_session_pending(self._db, current_session.id, now)
        await self._db.commit()

    async def execute_roll(
        self,
        *,
        current_user_id: int,
        roll_request: object,
    ) -> RollResponse:
        """Execute the full roll_dice flow."""
        user_id = current_user_id
        current_session = await get_or_create(self._db, user_id=user_id, existing_user=None)

        if current_session.pending_thread_id is not None:
            pending_thread = await self._db.get(Thread, current_session.pending_thread_id)
            pending_title = pending_thread.title if pending_thread else "another thread"
            pending_reference = f"'{pending_title}'" if pending_thread else "another thread"
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A roll is already pending for {pending_reference}. "
                    "Rate, snooze, or cancel the pending roll before rolling again."
                ),
            )

        current_die = await get_current_die_for_session(current_session, self._db)
        snoozed_ids = current_session.snoozed_thread_ids or []
        skipped_ids = current_session.skipped_thread_ids or []
        excluded_ids = await derive_effective_roll_excluded_thread_ids(
            self._db,
            user_id,
            session_snoozed_ids=snoozed_ids,
            session_skipped_ids=skipped_ids,
        )

        selection_bandwidth = (
            roll_request.bandwidth
            if hasattr(roll_request, 'bandwidth') and roll_request.bandwidth is not None
            else (current_session.active_bandwidth or DEFAULT_BANDWIDTH)
        )
        selection_intent = (
            roll_request.intent
            if hasattr(roll_request, 'intent') and roll_request.intent is not None
            else (current_session.active_intent or DEFAULT_INTENT)
        )

        artifacts = await self.select_pending_thread(
            user_id=user_id,
            current_session=current_session,
            current_die=current_die,
            excluded_ids=excluded_ids,
            selection_bandwidth=selection_bandwidth,
            selection_intent=selection_intent,
            selection_method_override=None,
        )

        selected_thread: Thread = artifacts["selected_thread"]
        event: Event = artifacts["event"]
        rec_context_create: RecommendationContextCreate = artifacts["rec_context_create"]

        self._db.add(event)
        await self._db.flush()

        rec_context = RecContextModel(
            event_id=event.id,
            schema_version=rec_context_create.schema_version,
            intent=rec_context_create.intent,
            intent_source=rec_context_create.intent_source,
            intent_confidence=rec_context_create.intent_confidence,
            bandwidth=rec_context_create.bandwidth,
            bandwidth_source=rec_context_create.bandwidth_source,
            bandwidth_confidence=rec_context_create.bandwidth_confidence,
            candidate_factors=[f.model_dump() for f in rec_context_create.candidate_factors]
            if rec_context_create.candidate_factors else None,
            final_weight=rec_context_create.final_weight,
            random_bypass=rec_context_create.random_bypass,
            balanced_neutrality=rec_context_create.balanced_neutrality,
            effort_minutes=rec_context_create.effort_minutes,
            effort_band=rec_context_create.effort_band,
            effort_source=rec_context_create.effort_source,
            effort_confidence=rec_context_create.effort_confidence,
            effort_sample_count=rec_context_create.effort_sample_count,
        )
        await insert_recommendation_context(self._db, rec_context)

        now = datetime.now(UTC)
        await update_session_pending_thread(self._db, current_session.id, selected_thread.id, now)

        await self._db.commit()

        selected_index: int = artifacts["selected_index"]
        unread_count: int = artifacts["unread_count"]
        return await self.build_roll_response(
            selected_thread=selected_thread,
            current_die=current_die,
            selected_index=selected_index,
            unread_count=unread_count,
            snoozed_count=len(snoozed_ids),
        )

    async def execute_skip(self, current_user_id: int) -> RollResponse:
        """Execute the full skip_roll flow."""
        user_id = current_user_id
        current_session = await get_or_create(self._db, user_id=user_id, existing_user=None)

        skipped_thread_id = current_session.pending_thread_id
        if skipped_thread_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No pending roll to skip. Roll first.",
            )

        current_die = await get_current_die_for_session(current_session, self._db)
        snoozed_ids = current_session.snoozed_thread_ids or []
        existing_skipped_ids = list(current_session.skipped_thread_ids or [])
        excluded_ids = await derive_effective_roll_excluded_thread_ids(
            self._db,
            user_id,
            session_snoozed_ids=snoozed_ids,
            session_skipped_ids=existing_skipped_ids,
        )

        artifacts = await self.select_pending_thread(
            user_id=user_id,
            current_session=current_session,
            current_die=current_die,
            excluded_ids=[*excluded_ids, skipped_thread_id],
            selection_bandwidth=current_session.active_bandwidth or DEFAULT_BANDWIDTH,
            selection_intent=current_session.active_intent or DEFAULT_INTENT,
            selection_method_override="skip",
            empty_pool_detail="No alternative threads available to skip to",
        )

        selected_thread: Thread = artifacts["selected_thread"]
        event: Event = artifacts["event"]
        rec_context_create: RecommendationContextCreate = artifacts["rec_context_create"]

        self._db.add(event)
        await self._db.flush()

        rec_context = RecContextModel(
            event_id=event.id,
            schema_version=rec_context_create.schema_version,
            intent=rec_context_create.intent,
            intent_source=rec_context_create.intent_source,
            intent_confidence=rec_context_create.intent_confidence,
            bandwidth=rec_context_create.bandwidth,
            bandwidth_source=rec_context_create.bandwidth_source,
            bandwidth_confidence=rec_context_create.bandwidth_confidence,
            candidate_factors=[f.model_dump() for f in rec_context_create.candidate_factors]
            if rec_context_create.candidate_factors else None,
            final_weight=rec_context_create.final_weight,
            random_bypass=rec_context_create.random_bypass,
            balanced_neutrality=rec_context_create.balanced_neutrality,
            effort_minutes=rec_context_create.effort_minutes,
            effort_band=rec_context_create.effort_band,
            effort_source=rec_context_create.effort_source,
            effort_confidence=rec_context_create.effort_confidence,
            effort_sample_count=rec_context_create.effort_sample_count,
        )
        await insert_recommendation_context(self._db, rec_context)

        if skipped_thread_id not in existing_skipped_ids:
            existing_skipped_ids.append(skipped_thread_id)
            await update_session_skipped(self._db, current_session.id, existing_skipped_ids)

        now = datetime.now(UTC)
        await update_session_pending_thread(self._db, current_session.id, selected_thread.id, now)

        await self._db.commit()

        selected_index: int = artifacts["selected_index"]
        unread_count: int = artifacts["unread_count"]
        return await self.build_roll_response(
            selected_thread=selected_thread,
            current_die=current_die,
            selected_index=selected_index,
            unread_count=unread_count,
            snoozed_count=len(snoozed_ids),
        )

    async def record_skip_outcome(self, *, session_id: int, thread_id: int) -> None:
        """Record that a session's pending thread was abandoned by a skip (#3706).

        Persistence goes through ``app.repositories.roll_repository.insert_event``.
        Callers must invoke this BEFORE adding the replacement roll event to the
        session: both history readers resolve event order by
        ``(timestamp, id)`` (``get_session_with_thread_safe`` and
        ``project_decision_history``), so a skip saved after the replacement
        roll would hide the new pending comic's rolled result and would
        attribute the skip to the replacement roll attempt instead of the
        original one.

        Args:
            session_id: Session where the skip happened.
            thread_id: The pending thread that was skipped.
        """
        event = Event(type="rolled_but_skipped", session_id=session_id, thread_id=thread_id)
        await insert_event(self._db, event)
        # Flush now so this event gets the earlier timestamp and id before the
        # replacement roll event is inserted.
        await self._db.flush()

    async def execute_override(self, *, thread_id: int, current_user: User) -> RollResponse:
        """Select an owned Thread using the active eligibility authority.

        Args:
            thread_id: Reader-selected Thread.
            current_user: Authenticated reader.

        Returns:
            Selected canonical issue and decision-time context.
        """
        db = self._db
        override_thread = await fetch_thread_by_id(db, thread_id, current_user.id, for_update=True)
        if not override_thread:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That series was not found",
            )

        eligibility = await get_execution_eligibility(db, current_user.id)
        if (
            override_thread.is_blocked
            if eligibility is None
            else thread_id not in eligibility.candidate_ids()
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f'"{override_thread.title}" is blocked and cannot be selected',
            )

        if override_thread.status != "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f'"{override_thread.title}" is {override_thread.status} '
                    "and cannot be selected"
                ),
            )

        current_session = await get_or_create(
            db, user_id=current_user.id, existing_user=current_user
        )
        current_session_id = current_session.id
        current_die = await get_current_die_for_session(current_session, db)

        override_thread_id = override_thread.id
        override_thread_title = override_thread.title
        override_thread_format = normalize_format_value(override_thread.format)
        override_thread_queue_position = await display_position(self._db, override_thread)

        override_thread_issues_remaining = (
            await override_thread.get_issues_remaining(db)
            if eligibility is None
            else eligibility.unread_counts.get(thread_id, 0)
        )
        override_thread_total_issues = override_thread.total_issues
        override_thread_reading_progress = override_thread.reading_progress
        override_thread_issue_id = None
        override_thread_issue_number = None
        if eligibility is not None:
            override_thread_issue_id = eligibility.threads[thread_id].next_issue_id
            override_thread_issue_number = eligibility.issue_numbers.get(override_thread_issue_id)
        elif override_thread.uses_issue_tracking() and override_thread.next_unread_issue_id:
            next_issue = await fetch_issue_by_id(db, override_thread.next_unread_issue_id)
            if next_issue and next_issue.status == "unread":
                override_thread_issue_id = next_issue.id
                override_thread_issue_number = next_issue.issue_number

        snoozed_ids = (
            list(current_session.snoozed_thread_ids) if current_session.snoozed_thread_ids else []
        )

        if eligibility is not None and override_thread_id in (
            current_session.skipped_thread_ids or []
        ):
            raise HTTPException(status_code=400, detail="Unskip this Thread before selecting it")

        # Issue #3446: the "Pick manually" picker lists the current session's snoozed
        # series on purpose, so an explicit override must succeed and leave the durable
        # session snooze untouched (#293) — the series stays snoozed after the manual
        # read. A thread that is only on durable cross-session snooze backoff, never
        # surfaced in that picker, stays excluded.
        derived_snoozed_ids = await derive_cross_session_excluded_thread_ids(db, current_user.id)
        if override_thread_id in derived_snoozed_ids and override_thread_id not in snoozed_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f'"{override_thread_title}" is on session-based snooze backoff and '
                    "cannot be overridden yet."
                ),
            )

        # Issue #3467: a double-clicked "Pick this series" must log a single ROLLED
        # event. Both signals must agree: the session still points at this thread
        # (so the pick is live and unconsumed) and the newest event is already the
        # override for it. A random roll, a rate, a snooze, a dismiss, or a
        # different pick breaks one of those signals, so a later pick of the same
        # series is treated as genuinely new and still records its own event.
        latest_event = await fetch_latest_session_event(db, current_session_id)
        pending_thread_id = await fetch_pending_thread_id(db, current_session_id)
        is_duplicate_override = (
            pending_thread_id == override_thread_id
            and latest_event is not None
            and latest_event.type == "roll"
            and latest_event.selection_method == "override"
            and latest_event.selected_thread_id == override_thread_id
        )
        if is_duplicate_override:
            snoozed_count = len(snoozed_ids)
            return RollResponse(
                thread_id=override_thread_id,
                title=override_thread_title,
                format=override_thread_format,
                issues_remaining=override_thread_issues_remaining,
                queue_position=override_thread_queue_position,
                die_size=current_die,
                result=0,
                offset=snoozed_count,
                snoozed_count=snoozed_count,
                issue_id=override_thread_issue_id,
                issue_number=override_thread_issue_number,
                next_issue_id=override_thread_issue_id,
                next_issue_number=override_thread_issue_number,
                total_issues=override_thread_total_issues,
                reading_progress=override_thread_reading_progress,
                explanation=get_primary_explanation([]),
            )

        # Decision-time context is purely observational: it records the estimate
        # that existed when this roll happened and never changes the selection.
        effort_estimate = await compute_effort_estimate(
            db,
            user_id=current_user.id,
            thread_id=override_thread_id,
            issue_id=override_thread_issue_id,
        )
        recommendation_settings = get_recommendation_settings()
        control_mode = recommendation_settings.control_mode
        algorithm_version = recommendation_algorithm_version(control_mode)
        override_candidate_weights: list[dict[str, object]] = [
            {
                "candidate_id": override_thread_id,
                "weight": 1.0,
                "reasons": [],
                "factors": [],
            }
        ]
        recommendation_context = build_recommendation_context(
            effort_estimate,
            thread_id=override_thread_id,
            issue_id=override_thread_issue_id,
            issue_number=override_thread_issue_number,
            candidate_weights=override_candidate_weights,
            bandwidth="balanced",
            bandwidth_source="manual_override",
            bandwidth_confidence=1.0,
            random_bypass=False,
            balanced_neutrality=True,
            selected_weight=1.0,
            algorithm_version=algorithm_version,
            control_mode=control_mode,
        )

        effort_estimate_str = (
            effort_estimate.band if isinstance(effort_estimate, EffortEstimate) else effort_estimate
        )

        event = Event(
            type="roll",
            session_id=current_session_id,
            selected_thread_id=override_thread_id,
            die=current_die,
            result=0,
            selection_method="override",
            recommendation_reason_codes=[],
            recommendation_context=recommendation_context,
            issue_id=override_thread_issue_id,
            issue_number=override_thread_issue_number,
            rolling_recommendation_context=self._build_rolling_recommendation_context(
                die_size=current_die,
                selected_queue_position=override_thread_queue_position,
                bounded_candidate_ids=[override_thread_id],
                selected_index=0,
                selection_method="override",
                session_timezone=current_session.timezone,
                selected_thread_last_rating=override_thread.last_rating,
                selected_thread_last_activity_at=override_thread.last_activity_at,
                effort_estimate=effort_estimate_str,
                algorithm_version=algorithm_version,
                control_mode=control_mode,
            ),
        )
        db.add(event)

        context_data = RecommendationContextCreate(
            schema_version=2,
            intent="balanced",
            intent_source="manual_override",
            intent_confidence=1.0,
            bandwidth="balanced",
            bandwidth_source="manual_override",
            bandwidth_confidence=1.0,
            candidate_factors=None,
            final_weight=1.0,
            random_bypass=False,
            balanced_neutrality=True,
            effort_minutes=round(effort_estimate.minutes, 2)
            if effort_estimate.minutes is not None
            else None,
            effort_band=effort_estimate.band,
            effort_source=effort_estimate.source.value,
            effort_confidence=round(effort_estimate.confidence, 3),
            effort_sample_count=effort_estimate.sample_count,
        )

        await insert_event(db, event)
        await db.flush()

        rec_context = RecContextModel(
            event_id=event.id,
            schema_version=context_data.schema_version,
            intent=context_data.intent,
            intent_source=context_data.intent_source,
            intent_confidence=context_data.intent_confidence,
            bandwidth=context_data.bandwidth,
            bandwidth_source=context_data.bandwidth_source,
            bandwidth_confidence=context_data.bandwidth_confidence,
            candidate_factors=[f.model_dump() for f in context_data.candidate_factors]
            if context_data.candidate_factors
            else None,
            final_weight=context_data.final_weight,
            random_bypass=context_data.random_bypass,
            balanced_neutrality=context_data.balanced_neutrality,
            effort_minutes=context_data.effort_minutes,
            effort_band=context_data.effort_band,
            effort_source=context_data.effort_source,
            effort_confidence=context_data.effort_confidence,
            effort_sample_count=context_data.effort_sample_count,
        )
        await insert_recommendation_context(db, rec_context)

        await update_session_pending_thread(
            db, current_session_id, override_thread_id, datetime.now(UTC)
        )

        await db.commit()

        snoozed_count = len(snoozed_ids)
        offset = snoozed_count

        return RollResponse(
            thread_id=override_thread_id,
            title=override_thread_title,
            format=override_thread_format,
            issues_remaining=override_thread_issues_remaining,
            queue_position=override_thread_queue_position,
            die_size=current_die,
            result=0,
            offset=offset,
            snoozed_count=snoozed_count,
            issue_id=override_thread_issue_id,
            issue_number=override_thread_issue_number,
            next_issue_id=override_thread_issue_id,
            next_issue_number=override_thread_issue_number,
            total_issues=override_thread_total_issues,
            reading_progress=override_thread_reading_progress,
            explanation=get_primary_explanation([]),
        )
