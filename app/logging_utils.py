"""Narrative logging utilities for user journey tracking."""

import logging

logger = logging.getLogger("narrative")


def log_session_start(session_id: int, die: int, user_id: int) -> None:
    """Log session start event."""
    logger.info(
        f"📖 Session #{session_id} started | User {user_id} begins reading journey with d{die}"
    )
    logger.info(
        f"📖 Session #{session_id} started | User {user_id} begins reading journey with d{die}"
    )


def log_roll(
    session_id: int, thread_title: str, die: int, result: int, selection_method: str
) -> None:
    """Log dice roll event."""
    method_emoji = "🎯" if selection_method == "override" else "🎲"
    logger.info(
        f"{method_emoji} Session #{session_id} rolled d{die} → {result} | Fate selects: {thread_title}"
    )


def log_skip(session_id: int, thread_title: str) -> None:
    """Log thread skip event."""
    logger.info(f"⏭️ Session #{session_id} skipped: {thread_title} | Maybe next time")


def log_rate(
    session_id: int,
    thread_title: str,
    rating: float,
    issues_read: int,
    die_before: int,
    die_after: int,
    queue_move: str,
) -> None:
    """Log thread rating event."""
    direction = "↓" if die_after < die_before else "↑"
    queue_emoji = "⬆️" if queue_move == "front" else "⬇️"
    logger.info(
        f"✨ Session #{session_id} rated '{thread_title}' {rating}/5.0 "
        f"| Read {issues_read} issues | Die {die_before}{direction}{die_after} | Queue {queue_emoji}"
    )


def log_thread_complete(session_id: int, thread_title: str) -> None:
    """Log thread completion event."""
    logger.info(f"🏁 Session #{session_id} completed '{thread_title}' | Another journey finished")


def log_thread_add(thread_title: str, format: str, issues: int) -> None:
    """Log new thread creation event."""
    logger.info(f"➕ New thread added: '{thread_title}' ({format}) | {issues} issues to read")


def log_thread_reactivate(thread_title: str, issues: int) -> None:
    """Log thread reactivation event."""
    logger.info(f"🔄 Thread reactivated: '{thread_title}' | {issues} fresh issues")


def log_thread_delete(thread_title: str) -> None:
    """Log thread deletion event."""
    logger.info(f"🗑️ Thread deleted: '{thread_title}' | Farewell")


def log_queue_move(thread_title: str, position: str, reason: str) -> None:
    """Log queue position change event."""
    logger.info(f"📋 '{thread_title}' moved to {position} queue | {reason}")


def log_session_end(session_id: int, duration_desc: str = "active period") -> None:
    """Log session end event."""
    logger.info(f"🎬 Session #{session_id} ended | Closing {duration_desc}")
