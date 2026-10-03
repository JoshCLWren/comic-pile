"""Guest demo roll API routes."""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import limiter
from app.models import Event, Issue, ReadingSession, Thread
from app.models.recommendation_context import RecommendationContext
from app.models.thread import normalize_format_value
from app.schemas import (
    RollBootstrapResponse,
    RollBootstrapThread,
    RollRequest,
    RollResponse,
    SessionMode,
)
from app.schemas.recommendation_context import (
    RecommendationContextCreate,
)

router = APIRouter(tags=["guest-demo"])
logger = logging.getLogger(__name__)


class GuestDemoService:
    """Service for managing guest demo state and data."""
    
    def __init__(self, db: AsyncSession) -> None:
        """Initialize the guest demo service.
        
        Args:
            db: Async database session for operations.
        """
        self._db = db
    
    async def get_demo_threads(self) -> list[Thread]:
        """Get pre-configured demo threads for guest rolls."""
        # Fetch sample threads that are marked as demo threads
        result = await self._db.execute(
            select(Thread)
            .where(Thread.is_demo_thread)
            .where(Thread.status == "active")
            .where(not Thread.is_blocked)
            .order_by(Thread.queue_position)
            .limit(20)  # Limit to a reasonable number for demo
        )
        return list(result.scalars().all())
    
    async def create_demo_session(self) -> ReadingSession:
        """Create a temporary demo session for guest users."""
        demo_session = ReadingSession(
            user_id=0,  # Special user ID for demo sessions
            started_at=datetime.now(UTC),
            timezone="UTC",  # Default timezone for demo
            active_bandwidth="balanced",
            active_intent="balanced",
            predicted_bandwidth="balanced",
            predicted_intent="balanced",
            bandwidth_source="demo",
            intent_source="demo",
        )
        self._db.add(demo_session)
        await self._db.flush()
        await self._db.refresh(demo_session)
        return demo_session
    
    async def cleanup_old_demo_sessions(self) -> None:
        """Clean up demo sessions older than 24 hours."""
        cutoff_time = datetime.now(UTC) - timedelta(hours=24)
        
        result = await self._db.execute(
            select(ReadingSession)
            .where(ReadingSession.user_id == 0)  # Demo sessions
            .where(ReadingSession.started_at < cutoff_time)
        )
        old_sessions = result.scalars().all()
        
        for session in old_sessions:
            # Delete related events and recommendation contexts
            await self._db.execute(
                select(Event).where(Event.session_id == session.id)
            )
            await self._db.execute(
                select(RecommendationContext).where(RecommendationContext.event_id.in_(
                    select(Event.id).where(Event.session_id == session.id)
                ))
            )
            await self._db.delete(session)
        
        if old_sessions:
            await self._db.commit()


async def get_demo_service(db: AsyncSession) -> GuestDemoService:
    """Get guest demo service instance."""
    # Clean up old demo sessions first
    service = GuestDemoService(db)
    await service.cleanup_old_demo_sessions()
    return service


def _build_guest_roll_response(
    *,
    selected_thread: Thread,
    unread_count: int,
    issue_number: str | None,
    selected_thread_issue_id: int | None,
    selected_thread_issue_number: str | None,
    current_die: int,
    selected_index: int,
    snoozed_count: int,
) -> RollResponse:
    """Build roll response for guest demo."""
    return RollResponse(
        thread_id=selected_thread.id,
        title=f"[DEMO] {selected_thread.title}",  # Mark as demo
        format=normalize_format_value(selected_thread.format),
        issues_remaining=unread_count,
        queue_position=selected_thread.queue_position,
        die_size=current_die,
        result=selected_index + 1,
        offset=snoozed_count,
        snoozed_count=snoozed_count,
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
        next_issue_id=selected_thread_issue_id,
        next_issue_number=selected_thread_issue_number,
        total_issues=selected_thread.total_issues,
        reading_progress=selected_thread.reading_progress,
        explanation="Demo selection - try the full experience!",
    )


@router.post("/demo-roll", response_model=RollResponse)
@limiter.limit("5/minute")  # Much stricter rate limit for demo
async def guest_demo_roll(
    request: Request,
    db: AsyncSession = Depends(get_db),
    roll_request: RollRequest = Body(default_factory=RollRequest),
) -> RollResponse:
    """Perform a guest demo roll without authentication.
    
    Args:
        request: FastAPI request object for rate limiting.
        db: SQLAlchemy session for database operations.
        roll_request: The roll request.
        
    Returns:
        RollResponse with selected thread and die result.
        
    Raises:
        HTTPException: If no demo threads available.
    """
    demo_service = await get_demo_service(db)
    
    # Get demo session
    current_session = await demo_service.create_demo_session()
    
    # Get demo threads
    demo_threads = await demo_service.get_demo_threads()
    if not demo_threads:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No demo threads available. Please try again later.",
        )
    
    # Simple random selection for demo (no complex recommendation logic)
    import random
    selected_thread = random.choice(demo_threads)
    selected_index = demo_threads.index(selected_thread)
    
    # Get issue information if available
    selected_thread_issue_id = None
    selected_thread_issue_number = None
    if selected_thread.uses_issue_tracking() and selected_thread.next_unread_issue_id:
        issue_result = await db.execute(
            select(Issue).where(Issue.id == selected_thread.next_unread_issue_id)
        )
        next_issue = issue_result.scalar_one_or_none()
        if next_issue and next_issue.status == "unread":
            selected_thread_issue_id = next_issue.id
            selected_thread_issue_number = next_issue.issue_number
    
    # Get current die size for demo
    current_die = 6  # Fixed die size for demo
    
    # Create a simple event for tracking
    event = Event(
        type="demo_roll",
        session_id=current_session.id,
        selected_thread_id=selected_thread.id,
        die=current_die,
        result=selected_index + 1,
        selection_method="demo_random",
        recommendation_reason_codes=["demo_selection"],
        recommendation_context={
            "schema_version": 1,
            "demo_mode": True,
            "thread_id": selected_thread.id,
            "thread_title": selected_thread.title,
        },
        issue_id=selected_thread_issue_id,
        issue_number=selected_thread_issue_number,
    )
    db.add(event)
    
    # Create recommendation context
    rec_context_create = RecommendationContextCreate(
        schema_version=2,
        intent="balanced",
        intent_source="demo",
        intent_confidence=1.0,
        bandwidth="balanced",
        bandwidth_source="demo",
        bandwidth_confidence=1.0,
        candidate_factors=None,
        final_weight=1.0,
        random_bypass=True,
        balanced_neutrality=True,
        effort_minutes=None,
        effort_band="unknown",
        effort_source="demo",
        effort_confidence=1.0,
        effort_sample_count=0,
    )
    
    rec_context = RecommendationContext(
        event_id=event.id,
        schema_version=rec_context_create.schema_version,
        intent=rec_context_create.intent,
        intent_source=rec_context_create.intent_source,
        intent_confidence=rec_context_create.intent_confidence,
        bandwidth=rec_context_create.bandwidth,
        bandwidth_source=rec_context_create.bandwidth_source,
        bandwidth_confidence=rec_context_create.bandwidth_confidence,
        candidate_factors=None,
        final_weight=rec_context_create.final_weight,
        random_bypass=rec_context_create.random_bypass,
        balanced_neutrality=rec_context_create.balanced_neutrality,
        effort_minutes=rec_context_create.effort_minutes,
        effort_band=rec_context_create.effort_band,
        effort_source=rec_context_create.source,
        effort_confidence=rec_context_create.effort_confidence,
        effort_sample_count=rec_context_create.effort_sample_count,
    )
    db.add(rec_context)
    
    # Set pending thread for demo session
    current_session.pending_thread_id = selected_thread.id
    current_session.pending_thread_updated_at = datetime.now(UTC)
    
    # Extract thread data before commit to avoid MissingGreenlet
    issues_remaining = selected_thread.get_issues_remaining(db) if hasattr(selected_thread, 'get_issues_remaining') else 1
    
    await db.commit()
    
    return _build_guest_roll_response(
        selected_thread=selected_thread,
        unread_count=issues_remaining,
        issue_number=selected_thread_issue_number,
        selected_thread_issue_id=selected_thread_issue_id,
        selected_thread_issue_number=selected_thread_issue_number,
        current_die=current_die,
        selected_index=selected_index,
        snoozed_count=0,
    )


@router.get("/demo-bootstrap", response_model=RollBootstrapResponse)
async def guest_demo_bootstrap(
    db: AsyncSession = Depends(get_db),
    timezone: str | None = Query(default=None, description="Browser IANA timezone identifier"),
) -> RollBootstrapResponse:
    """Return bootstrap data for guest demo roll.
    
    Args:
        db: Async database session.
        timezone: Optional browser-resolved IANA timezone identifier.
        
    Returns:
        RollBootstrapResponse with demo session state and demo threads.
    """
    demo_service = await get_demo_service(db)
    
    # Create demo session
    current_session = await demo_service.create_demo_session()
    
    # Get demo threads
    demo_threads = await demo_service.get_demo_threads()
    
    # Build demo thread pool
    roll_pool = [
        RollBootstrapThread(
            id=thread.id,
            title=f"[DEMO] {thread.title}",
            format=normalize_format_value(thread.format),
            issue_id=thread.next_unread_issue_id,
            issue_number=None,  # Will be populated if needed
            route_labels=["demo", "sample"],
        )
        for thread in demo_threads
    ]
    
    # Get session info
    current_die = 6  # Fixed die size for demo
    manual_die = None
    pending_thread_id = current_session.pending_thread_id
    
    return RollBootstrapResponse(
        current_die=current_die,
        manual_die=manual_die,
        pending_thread_id=pending_thread_id,
        last_rolled_result=None,
        session_mode=SessionMode(
            active_bandwidth="balanced",
            predicted_bandwidth="balanced",
            bandwidth_confidence=1.0,
            bandwidth_source="demo",
            bandwidth_version="demo_v1",
            active_intent="balanced",
            predicted_intent="balanced",
            intent_confidence=1.0,
            intent_source="demo",
            intent_version="demo_v1",
            session_mode_correction_guidance=None,
        ),
        active_thread=None,
        roll_recovery=None,
        bandwidth={
            "predicted_bandwidth": "balanced",
            "active_bandwidth": "balanced",
            "confidence": 1.0,
            "source": "demo",
            "mode_version": "demo_v1",
        },
        roll_pool=roll_pool,
        snoozed_threads=[],
        snoozed_count=0,
        skipped_thread_ids=[],
        skipped_threads=[],
        blocked_count=0,
        blocked_threads=[],
        stale_thread_count=0,
        stale_thread=None,
        session_id=current_session.id,
        user_id=0,  # Demo user
        timezone=current_session.timezone,
    )