"""Focused unit coverage for advisory title resemblance scoring (#3612)."""

import pytest

from app.services.title_similarity import (
    MIN_TITLE_SIMILARITY,
    normalize_title,
    significant_title_tokens,
    title_similarity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Spider-Man", "spider man"),
        ("  Amazing   SPIDER-MAN  ", "amazing spider man"),
        ("X-Men: Legacy", "x men legacy"),
        ("", ""),
        ("---", ""),
    ],
)
def test_normalize_title_collapses_punctuation_and_case(raw: str, expected: str) -> None:
    """Hyphens, spacing, and case never change the title being compared."""
    assert normalize_title(raw) == expected


@pytest.mark.parametrize(
    ("existing", "proposed"),
    [
        ("Spider-Man", "Amazing Spider-Man"),
        ("Amazing Spider-Man", "Spider-Man"),
        ("The Uncanny X-Men", "Uncanny X-Men"),
    ],
)
def test_phrase_containment_scores_a_possible_match(existing: str, proposed: str) -> None:
    """A run title that contains another run title is worth warning about."""
    assert title_similarity(proposed, existing) >= MIN_TITLE_SIMILARITY


@pytest.mark.parametrize(
    ("existing", "proposed"),
    [
        ("Saga", "Daredevil"),
        ("Batman", "Saga"),
        ("", "Saga"),
    ],
)
def test_unrelated_titles_do_not_match(existing: str, proposed: str) -> None:
    """Different titles are not duplicates merely because both are comics."""
    assert title_similarity(proposed, existing) < MIN_TITLE_SIMILARITY


def test_same_normalized_title_is_the_highest_score() -> None:
    """Formatting differences in one title still compare as the same title."""
    assert title_similarity("spider man", "Spider-Man") == 1.0


def test_token_overlap_handles_shared_words_in_different_orders() -> None:
    """Shared meaningful words score above the advisory threshold."""
    assert title_similarity("Spectacular Spider-Man", "Amazing Spider-Man") >= MIN_TITLE_SIMILARITY


def test_significant_tokens_skip_stopword_fragments() -> None:
    """Short connective fragments never become the whole candidate filter."""
    assert significant_title_tokens("x men legacy") == ("legacy", "men")


def test_significant_tokens_fall_back_for_short_titles() -> None:
    """A short title still produces a usable search token."""
    assert significant_title_tokens("v") == ("v",)
