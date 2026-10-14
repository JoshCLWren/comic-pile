"""Roll business logic and orchestration.

Services own business rules, transaction boundaries (commit/rollback),
and cache invalidation. Query construction lives in
``app.repositories.roll_repository``. HTTP status mapping lives in routers.
"""

import logging
from datetime import UTC, datetime
from typing import TypedDict

# Import comic_pile first to resolve circular dependency with
# comic_pile.bandwidth -> app.services.reading_effort.
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, ReadingSession, Tag, Thread, User
from app.models.thread import normalize_format_value
from app.models.recommendation_context import RecommendationContext as RecContextModel
from app.repositories import roll_tag_exclusion_repository, tag_repository, thread_repository
from app.repositories.roll_repository import (
    fetch_issue_by_id,
    fetch_session_events,
    insert_recommendation_context,
    update_session_pending_thread,
    update_session_skipped,
)
from app.services.reading_effort import (
    EffortEstimate,
    build_recommendation_context,
    compute_effort_estimate,
)
from app.services.bandwidth_selection import select_bandwidth_weighted
from app.schemas.recommendation_context import (
    CandidateFactor,
    RecommendationContextCreate,
)
from app.services.roll_tag_exclusion_service import ExcludeTagAndRerollResult
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
from comic_pile.reading_session import get_current_die_for_session, get_or_create

from app.config import get_recommendation_settings
from app.schemas import RollResponse

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


class RollService:
    """Service for roll orchestration.

    Owns the core roll selection, commit, and response-building logic
    previously embedded in ``app.api.roll``.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the RollService with a database session."""
        self._db = db

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
        from comic_pile.queue import (
            get_roll_pool_rows,
            partition_pool_by_tag_exclusions,
        )

        rows = await get_roll_pool_rows(
            user_id, self._db, excluded_ids,
        )
        excluded_tags = await roll_tag_exclusion_repository.list_excluded_tags(
            self._db, user_id
        )
        if excluded_tags:
            excluded_tag_ids = [tag.id for tag in excluded_tags]
            candidates = [
                (row[0].id, row[0].next_unread_issue_id) for row in rows
            ]
            effective_tag_ids = (
                await roll_tag_exclusion_repository.fetch_effective_tag_ids_for_candidates(
                    self._db, user_id, candidates
                )
            )
            eligible_rows, tag_ineligible = partition_pool_by_tag_exclusions(
                rows, excluded_tag_ids, effective_tag_ids
            )
            bounded_rows = eligible_rows[:current_die]
            if not bounded_rows and tag_ineligible:
                raise HTTPException(
                    status_code=400, detail=self._tag_exclusion_empty_pool_detail(
                        excluded_tags
                    ),
                )
        else:
            bounded_rows = rows[:current_die]
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
        if selected_thread.uses_issue_tracking() and selected_thread.next_unread_issue_id:
            if unread_count > 0 and issue_number is not None:
                selected_thread_issue_id = selected_thread.next_unread_issue_id
                selected_thread_issue_number = issue_number
            else:
                issue = await fetch_issue_by_id(self._db, selected_thread.next_unread_issue_id)
                if issue and issue.status == "unread":
                    selected_thread_issue_id = issue.id
                    selected_thread_issue_number = issue.issue_number

        effort_estimates: list[EffortEstimate] = []
        for thread, _unread_count, _issue_number in bounded_rows:
            issue_id = thread.next_unread_issue_id if thread.uses_issue_tracking() else None
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

    @staticmethod
    def _tag_exclusion_empty_pool_detail(excluded_tags: list[Tag]) -> str:
        """Build the explanatory detail for a tag-exclusion-emptied pool.

        Exclusions are never silently ignored: when they eliminate every
        otherwise-rollable candidate the error names the active exclusions
        responsible and points at removal and retry instead of falling back
        to an unfiltered pool.

        Args:
            excluded_tags: The user's active excluded tags.

        Returns:
            Human-readable error detail naming the responsible exclusions.
        """
        names = ", ".join(tag.name for tag in excluded_tags)
        return (
            "No candidates satisfy the current tag exclusions "
            f"(excluded: {names}). Remove one or more tag exclusions and roll again."
        )

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

    def build_roll_response(
        self,
        *,
        selected_thread: Thread | None = None,
        thread_attrs: dict | None = None,
        current_die: int,
        selected_index: int,
        unread_count: int,
        snoozed_count: int,
    ) -> RollResponse:
        """Convert selection artifacts into the public RollResponse.

        Either ``selected_thread`` or ``thread_attrs`` must be provided.
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
            queue_position = selected_thread.queue_position
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
            issue_id=None,
            issue_number=None,
            next_issue_id=None,
            next_issue_number=None,
            total_issues=total_issues,
            reading_progress=reading_progress,
            explanation=None,
        )

    async def execute_dismiss_pending(self, current_user_id: int) -> None:
        """Execute the dismiss_pending_roll flow."""
        current_session = await get_or_create(self._db, user_id=current_user_id, existing_user=None)
        now = datetime.now(UTC)
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
            excluded_ids=[*snoozed_ids, *skipped_ids],
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
        return self.build_roll_response(
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

        artifacts = await self.select_pending_thread(
            user_id=user_id,
            current_session=current_session,
            current_die=current_die,
            excluded_ids=[*snoozed_ids, *existing_skipped_ids, skipped_thread_id],
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
        return self.build_roll_response(
            selected_thread=selected_thread,
            current_die=current_die,
            selected_index=selected_index,
            unread_count=unread_count,
            snoozed_count=len(snoozed_ids),
        )

    async def _persist_selection(
        self,
        *,
        current_session: ReadingSession,
        selected_thread: Thread,
        event: Event,
        rec_context_create: RecommendationContextCreate,
    ) -> None:
        """Persist one selection's event, recommendation context, and pending state.

        Shared by the neutral reroll path so exclusion-driven rerolls record
        exactly what an ordinary roll records — and nothing else.

        Args:
            current_session: The user's active reading session.
            selected_thread: The newly selected thread.
            event: The roll event to persist.
            rec_context_create: The recommendation context payload to persist.
        """
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
        await update_session_pending_thread(
            self._db, current_session.id, selected_thread.id, now
        )

    async def execute_neutral_reroll(self, *, user_id: int) -> RollResponse:
        """Select another eligible result without any preference side effects.

        Used after a mid-roll tag exclusion invalidates the pending result.
        The reroll runs normal Roll selection over the exclusion-filtered pool
        and deliberately touches nothing else: no snooze or skip entries, no
        die change, no bandwidth correction, no queue move, and no rating or
        taste writes. The caller must have cleared the pending roll first.

        Args:
            user_id: The user to reroll for.

        Returns:
            RollResponse for the newly selected thread.

        Raises:
            HTTPException: 400 when no eligible candidate remains, 409 when a
                pending roll still exists.
        """
        current_session = await get_or_create(
            self._db, user_id=user_id, existing_user=None
        )

        if current_session.pending_thread_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A roll is already pending. Clear it before rerolling.",
            )

        current_die = await get_current_die_for_session(current_session, self._db)
        snoozed_ids = current_session.snoozed_thread_ids or []
        skipped_ids = current_session.skipped_thread_ids or []

        artifacts = await self.select_pending_thread(
            user_id=user_id,
            current_session=current_session,
            current_die=current_die,
            excluded_ids=[*snoozed_ids, *skipped_ids],
            selection_bandwidth=current_session.active_bandwidth or DEFAULT_BANDWIDTH,
            selection_intent=current_session.active_intent or DEFAULT_INTENT,
            selection_method_override=None,
        )

        selected_thread: Thread = artifacts["selected_thread"]
        selected_index: int = artifacts["selected_index"]
        unread_count: int = artifacts["unread_count"]

        await self._persist_selection(
            current_session=current_session,
            selected_thread=selected_thread,
            event=artifacts["event"],
            rec_context_create=artifacts["rec_context_create"],
        )

        await self._db.commit()

        return self.build_roll_response(
            selected_thread=selected_thread,
            current_die=current_die,
            selected_index=selected_index,
            unread_count=unread_count,
            snoozed_count=len(snoozed_ids),
        )

    async def execute_exclude_tag_and_reroll(
        self, *, user: User, tag_id: int
    ) -> ExcludeTagAndRerollResult:
        """Persist an account-wide tag exclusion, rerolling neutrally when needed.

        Implements the mid-roll behavior for issue #3033:

        1. persist the account-wide exclusion;
        2. when the currently pending issue's effective tags contain the
           excluded tag, invalidate/clear the now-ineligible pending result;
        3. automatically select another eligible result through normal Roll
           selection;
        4. record nothing as a snooze or negative preference signal.

        When no pending roll exists, or the pending result stays eligible, the
        exclusion is persisted and no reroll happens.

        Args:
            user: The requesting user.
            tag_id: Tag to exclude from Roll eligibility.

        Returns:
            The exclusion outcome, including the replacement roll when the
            pending result was invalidated.

        Raises:
            HTTPException: 404 when the tag does not exist or is not visible
                to the user; 400 when the exclusion empties the eligible pool.
        """
        tag = await tag_repository.get_tag_by_id(self._db, tag_id)
        if tag is None or (tag.scope == "private" and tag.owner_user_id != user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tag {tag_id} does not exist",
            )

        tag_id_value = tag.id
        await roll_tag_exclusion_repository.add_exclusion(
            self._db, user.id, tag_id_value
        )
        await self._db.commit()

        current_session = await get_or_create(
            self._db, user_id=user.id, existing_user=user
        )
        pending_thread_id = current_session.pending_thread_id
        if pending_thread_id is None:
            return ExcludeTagAndRerollResult(
                excluded_tag=tag, pending_invalidated=False, roll=None
            )

        pending_thread = await thread_repository.find_owned(
            self._db, user.id, pending_thread_id
        )
        if pending_thread is None:
            current_session.pending_thread_id = None
            current_session.pending_thread_updated_at = None
            await self._db.flush()
            roll = await self.execute_neutral_reroll(user_id=user.id)
            return ExcludeTagAndRerollResult(
                excluded_tag=tag, pending_invalidated=True, roll=roll
            )

        pending_thread_id_value = pending_thread.id
        pending_issue_id = pending_thread.next_unread_issue_id
        effective = await roll_tag_exclusion_repository.fetch_effective_tag_ids_for_candidates(
            self._db, user.id, [(pending_thread_id_value, pending_issue_id)]
        )
        if tag_id_value not in effective.get(pending_thread_id_value, set()):
            return ExcludeTagAndRerollResult(
                excluded_tag=tag, pending_invalidated=False, roll=None
            )

        current_session.pending_thread_id = None
        current_session.pending_thread_updated_at = None
        await self._db.flush()
        roll = await self.execute_neutral_reroll(user_id=user.id)
        return ExcludeTagAndRerollResult(
            excluded_tag=tag, pending_invalidated=True, roll=roll
        )
