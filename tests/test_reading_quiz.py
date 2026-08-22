"""Tests for the reading-mode quiz contract.

These cover every answer combination, the decoupling of copy from stable IDs,
and the deterministic resolution used by both the backend API and the frontend.
"""

from __future__ import annotations

import pytest

from app.services.reading_quiz import (
    QuizResolutionError,
    ReadingModeSource,
    all_answer_combinations,
    is_valid_reading_mode,
    list_quiz_questions,
    resolve_quiz_answers,
)


def test_every_combination_maps_to_valid_mode() -> None:
    """All answer combinations must produce a valid bandwidth/intent pair."""
    combinations = all_answer_combinations()
    assert len(combinations) == 12  # 3 brainpower x 4 pick

    for answers in combinations:
        mode = resolve_quiz_answers(answers)
        assert is_valid_reading_mode(mode.bandwidth, mode.intent)


def test_combination_axes_are_independent() -> None:
    """Each brainpower value maps to exactly one bandwidth across all picks."""
    for brainpower, expected_bandwidth in [
        ("easy", "light"),
        ("normal", "balanced"),
        ("substantial", "deep"),
    ]:
        for pick in ("momentum", "familiar", "explore", "random"):
            mode = resolve_quiz_answers({"brainpower": brainpower, "pick": pick})
            assert mode.bandwidth == expected_bandwidth

    for pick, expected_intent in [
        ("momentum", "momentum"),
        ("familiar", "familiar"),
        ("explore", "explore"),
        ("random", "random"),
    ]:
        for brainpower in ("easy", "normal", "substantial"):
            mode = resolve_quiz_answers({"brainpower": brainpower, "pick": pick})
            assert mode.intent == expected_intent


def test_copy_is_separate_from_stable_ids() -> None:
    """User-facing copy must not leak stable IDs and must remain changeable."""
    questions = list_quiz_questions()
    assert {q["id"] for q in questions} == {"brainpower", "pick"}

    by_id = {q["id"]: q for q in questions}
    assert by_id["brainpower"]["prompt"] == "How much brain do you have right now?"
    assert by_id["pick"]["prompt"] == "What kind of pick sounds good?"

    answer_ids = {a["id"] for q in questions for a in q["answers"]}
    assert answer_ids == {
        "easy",
        "normal",
        "substantial",
        "momentum",
        "familiar",
        "explore",
        "random",
    }
    # Answer labels (copy) are independent of the stable IDs.
    assert by_id["brainpower"]["answers"][0]["label"] == "Easy"


def test_unknown_question_is_rejected() -> None:
    with pytest.raises(QuizResolutionError):
        resolve_quiz_answers({"not_a_question": "easy", "pick": "random"})


def test_unknown_answer_is_rejected() -> None:
    with pytest.raises(QuizResolutionError):
        resolve_quiz_answers({"brainpower": "nope", "pick": "random"})


def test_partial_answers_are_rejected() -> None:
    with pytest.raises(QuizResolutionError):
        resolve_quiz_answers({"brainpower": "easy"})


def test_source_values_are_stable() -> None:
    assert ReadingModeSource.values() == {"quiz", "manual"}
    assert ReadingModeSource.QUIZ.value == "quiz"
    assert ReadingModeSource.MANUAL.value == "manual"
