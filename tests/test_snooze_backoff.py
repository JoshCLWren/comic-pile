"""Tests for snooze backoff sequence arithmetic.

These exercises target the pure policy module in ``comic_pile.snooze_backoff``
without any database, FastAPI, or SQLAlchemy dependency, matching the module's
documented contract of being unit-testable in isolation.
"""

from comic_pile.snooze_backoff import (
    compute_backoff_sessions,
    fibonacci,
    generate_sequence,
    is_eligible,
)

EXPECTED_SEQUENCE = [1, 1, 2, 2, 3, 3, 5, 5, 8, 8, 13, 13]


def test_fibonacci_sequence_starts_one_indexed() -> None:
    """Verify Fibonacci with F1=1, F2=1 as required by the issue."""
    assert fibonacci(1) == 1
    assert fibonacci(2) == 1
    assert fibonacci(3) == 2
    assert fibonacci(4) == 3
    assert fibonacci(5) == 5
    assert fibonacci(6) == 8
    assert fibonacci(7) == 13


def test_fibonacci_non_positive_returns_zero() -> None:
    """Non-positive indices return 0 rather than negative or undefined values."""
    assert fibonacci(0) == 0
    assert fibonacci(-1) == 0


def test_compute_backoff_sessions_matches_issue_sequence() -> None:
    """Snooze counts 1..12 produce exactly the issue-specified sequence."""
    for index, snooze_count in enumerate(range(1, len(EXPECTED_SEQUENCE) + 1), start=1):
        assert compute_backoff_sessions(snooze_count) == EXPECTED_SEQUENCE[index - 1]


def test_compute_backoff_sessions_specific_values() -> None:
    """Spot-check boundary and mid-sequence expected values."""
    assert compute_backoff_sessions(1) == 1
    assert compute_backoff_sessions(2) == 1
    assert compute_backoff_sessions(7) == 5
    assert compute_backoff_sessions(8) == 5
    assert compute_backoff_sessions(11) == 13
    assert compute_backoff_sessions(12) == 13


def test_compute_backoff_sessions_has_no_cap() -> None:
    """There is no application-level maximum; larger counts keep growing."""
    assert compute_backoff_sessions(23) > compute_backoff_sessions(12)
    assert compute_backoff_sessions(100) > compute_backoff_sessions(50)
    assert compute_backoff_sessions(100) != compute_backoff_sessions(1)


def test_generate_sequence_produces_repeated_fibonacci_pairs() -> None:
    """Generated sequence repeats each Fibonacci term twice in order."""
    sequence = generate_sequence(12)
    assert sequence == EXPECTED_SEQUENCE


def test_generate_sequence_is_deterministic() -> None:
    """Repeated generation yields identical results."""
    assert generate_sequence(12) == generate_sequence(12)


def test_generate_sequence_empty_limit() -> None:
    """A zero limit yields an empty sequence."""
    assert generate_sequence(0) == []


def test_is_eligible_boundary_equals_required_backoff() -> None:
    """A thread becomes eligible exactly when later sessions reach backoff."""
    assert is_eligible(0, 0) is True
    assert is_eligible(1, 0) is False
    assert is_eligible(1, 1) is True
    assert is_eligible(2, 0) is False
    assert is_eligible(2, 1) is True
    assert is_eligible(3, 1) is False
    assert is_eligible(3, 2) is True
    assert is_eligible(10, 8) is False
    assert is_eligible(10, 13) is True
    assert is_eligible(12, 12) is False
    assert is_eligible(12, 13) is True


def test_is_eligible_matches_issue_session_examples() -> None:
    """Issue calibration examples map to the eligibility boundaries."""
    # Each entry is (snooze_count, later_sessions, expected_eligibility).
    cases = [
        (1, 0, False),
        (1, 1, True),
        (2, 1, True),
        (3, 1, False),
        (3, 2, True),
        (7, 4, False),
        (7, 5, True),
        (11, 12, False),
        (11, 13, True),
    ]
    for snooze_count, later_sessions, expected in cases:
        assert is_eligible(snooze_count, later_sessions) is expected
