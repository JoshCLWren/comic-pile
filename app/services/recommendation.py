"""Thread recommendation service with explainable reasoning."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.thread import Thread
from app.models.user_preferences import UserPreferences


class ThreadScore:
    """Represents a scored thread with explanation codes."""

    def __init__(self, thread: Thread, score: float, reason_codes: list[str]) -> None:
        """Initialize a ThreadScore.

        Args:
            thread: The thread being scored.
            score: The computed score.
            reason_codes: List of reason codes explaining the score.
        """
        self.thread = thread
        self.score = score
        self.reason_codes = reason_codes


async def get_recommended_thread(
    user_id: int,
    db: AsyncSession,
    snoozed_ids: list[int] | None = None,
    die_size: int = 6,
) -> tuple[Thread, int, list[str]]:
    """Select a thread using recommendation algorithms and return the thread, index, and reason codes.
    
    Args:
        user_id: The user ID to filter threads by.
        db: The database session.
        snoozed_ids: Optional list of thread IDs to exclude from the pool.
        die_size: The current die size determining how many threads are in the pool.
        
    Returns:
        Tuple of (selected_thread, selected_index, reason_codes)
    """
    # Get the roll pool (active threads ordered by position)
    from comic_pile.queue import get_roll_pool_rows
    
    pool_rows = await get_roll_pool_rows(user_id, db, snoozed_ids)
    if not pool_rows:
        raise ValueError("No active threads available")
    
    # Bound the selection to the current die size
    bounded_rows = pool_rows[:die_size]
    pool_size = len(bounded_rows)
    
    if pool_size == 0:
        raise ValueError("No threads in roll pool after bounding")
    
    # Score each thread in the bounded pool
    scored_threads: list[ThreadScore] = []
    
    # Get user preferences for theme matching
    user_prefs_result = await db.execute(
        select(UserPreferences.theme).where(UserPreferences.user_id == user_id)
    )
    user_prefs = user_prefs_result.scalar_one_or_none()
    _ = user_prefs if user_prefs else "classic"  # default theme (unused for now)
    
    for thread, unread_count, _issue_number in bounded_rows:
        score = 0.0
        reason_codes: list[str] = []
        
        # Factor 1: Affinity based on last rating (0-0.4 points)
        if thread.last_rating is not None:
            # Normalize rating (assuming 0-5 scale) to 0-0.4 points
            affinity_score = (thread.last_rating / 5.0) * 0.4
            score += affinity_score
            if thread.last_rating >= 4.0:
                reason_codes.append("strong_affinity")
            elif thread.last_rating >= 3.0:
                reason_codes.append("moderate_affinity")
        
        # Factor 2: Read time estimate based on issues remaining (0-0.3 points)
        # Estimate ~2 minutes per issue, cap at 30 minutes (15 issues)
        if thread.uses_issue_tracking():
            # For issue-tracked threads, we'd need to query, but for simplicity
            # we'll use a placeholder - in reality this would be more complex
            estimated_minutes = min(unread_count * 2, 30)  # 2 mins per issue, max 30 mins
        else:
            # For legacy threads, use issues_remaining directly
            estimated_minutes = min(thread.issues_remaining * 2, 30)
        
        if estimated_minutes <= 5:
            time_score = 0.3  # Very quick read
            reason_codes.append("quick_read")
        elif estimated_minutes <= 15:
            time_score = 0.2  # Reasonable read time (~11 minutes)
            reason_codes.append("~11_minute_read")
        elif estimated_minutes <= 30:
            time_score = 0.1  # Longer read
            reason_codes.append("longer_read")
        else:
            time_score = 0.0  # Very long read
            
        score += time_score
        
        # Factor 3: Format/theme preference match (0-0.2 points)
        # This is a simplified check - in reality we'd map thread formats to theme preferences
        # For now, we'll give a small boost if we can determine it's a good fit
        # Since we don't have explicit format->theme mapping, we'll skip this for now
        # or give a small base score
        format_score = 0.1  # Base format compatibility
        score += format_score
        reason_codes.append("format_compatible")
        
        # Factor 4: Series momentum based on recent activity (0-0.1 points)
        if thread.last_activity_at:
            # Calculate hours since last activity
            hours_since = (datetime.now(UTC) - thread.last_activity_at).total_seconds() / 3600
            if hours_since < 1:  # Active in last hour
                momentum_score = 0.1
                reason_codes.append("recent_series_momentum")
            elif hours_since < 24:  # Active in last day
                momentum_score = 0.05
                reason_codes.append("some_series_activity")
            else:
                momentum_score = 0.0
        else:
            momentum_score = 0.0
            
        score += momentum_score
        
        # Add some randomness to prevent deterministic behavior (0-0.1 points)
        random_score = random.random() * 0.1
        score += random_score
        
        scored_threads.append(ThreadScore(thread, score, reason_codes))
    
    # Sort by score descending (highest score first)
    scored_threads.sort(key=lambda x: x.score, reverse=True)
    
    # Add some randomness to selection to avoid always picking the absolute top
    # We'll use a weighted selection where higher scores have better odds
    # but there's still a chance for lower-scored threads to be selected
    
    # Extract scores for weighting
    scores = [st.score for st in scored_threads]
    
    # Use softmax to convert scores to probabilities
    # Add small constant to prevent zero probabilities
    exp_scores = [pow(2.71828, s) for s in scores]  # e^score
    sum_exp_scores = sum(exp_scores)
    probabilities = [es / sum_exp_scores for es in exp_scores]
    
    # Select thread based on probabilities
    selected_index = random.choices(range(pool_size), weights=probabilities)[0]
    selected_thread_score = scored_threads[selected_index]
    
    # If no reason codes were generated, mark as pure random
    if not selected_thread_score.reason_codes:
        selected_thread_score.reason_codes = ["pure_random"]
    
    return selected_thread_score.thread, selected_index, selected_thread_score.reason_codes