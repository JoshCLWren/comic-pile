"""Snooze backoff policy module.

Defines the Fibonacci-based session backoff sequence that determines when a
snoozed thread becomes eligible for re-roll across reading sessions.

The sequence: 1, 1, 2, 2, 3, 3, 5, 5, 8, 8, 13, 13, ...
Formula: pair = ceil(snooze_count / 2), backoff_sessions = Fibonacci(pair + 1)

This module is deliberately free of FastAPI, SQLAlchemy, or database
dependencies so it can be unit-tested in isolation.
"""


def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (1-indexed, F1=1, F2=1).

    Args:
        n: 1-based index (fibonacci(1) = 1, fibonacci(2) = 1,
            fibonacci(3) = 2, fibonacci(4) = 3, ...).

    Returns:
        The nth Fibonacci number.
    """
    if n <= 0:
        return 0
    if n == 1 or n == 2:
        return 1
    a, b = 1, 1
    for _ in range(3, n + 1):
        a, b = b, a + b
    return b


def compute_backoff_sessions(snooze_count: int) -> int:
    """Compute the required number of later sessions for snooze eligibility.

    Uses the formula: pair = ceil(snooze_count / 2), backoff = Fibonacci(pair + 1).

    Args:
        snooze_count: Number of snooze events for the thread.

    Returns:
        The required number of later user sessions before the thread becomes eligible.
    """
    if snooze_count <= 0:
        return 0
    pair = (snooze_count + 1) // 2
    return fibonacci(pair + 1)


def is_eligible(snooze_count: int, later_session_count: int) -> bool:
    """Whether a thread is eligible given its snooze streak and later sessions.

    A thread with no snooze streak is always eligible. Otherwise it becomes
    eligible only once the number of later user sessions (sessions that started
    after the latest snooze event) reaches the required backoff.

    Args:
        snooze_count: Number of snooze events for the thread after the reset
            boundary (0 when there is no active streak).
        later_session_count: Number of that user's sessions that started after
            the latest snooze event.

    Returns:
        True when the thread may be re-rolled, False while it must stay out.
    """
    return snooze_count <= 0 or later_session_count >= compute_backoff_sessions(snooze_count)


def generate_sequence(limit: int) -> list[int]:
    """Generate the backoff sequence up to the given index.

    Args:
        limit: Number of terms to generate.

    Returns:
        List of backoff session counts: [1, 1, 2, 2, 3, 3, ...].
    """
    result: list[int] = []
    for i in range(1, limit + 1):
        result.append(compute_backoff_sessions(i))
    return result

