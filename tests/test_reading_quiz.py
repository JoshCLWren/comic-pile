"""Tests for the two-question reading-mode quiz contract (#1735 surface)."""

import pytest
from pydantic import ValidationError

from app.schemas.session import SessionModeUpdateRequest
from app.services.reading_quiz import (
    BANDWIDTH_QUESTION_ID,
    INTENT_QUESTION_ID,
    QUIZ_QUESTIONS,
    VALID_BANDWIDTHS,
    VALID_INTENTS,
    QuizResolutionError,
    all_answer_combinations,
    is_valid_reading_mode,
    list_quiz_questions,
    resolve_quiz_answers,
)


@pytest.mark.parametrize(
    ("question_id", "answer_id", "expected_bandwidth", "expected_intent"),
    [
        (BANDWIDTH_QUESTION_ID, "easy", "light", None),
        (BANDWIDTH_QUESTION_ID, "normal", "balanced", None),
        (BANDWIDTH_QUESTION_ID, "substantial", "deep", None),
        (INTENT_QUESTION_ID, "momentum", None, "momentum"),
        (INTENT_QUESTION_ID, "familiar", None, "familiar"),
        (INTENT_QUESTION_ID, "explore", None, "explore"),
        (INTENT_QUESTION_ID, "random", None, "random"),
    ],
)
def test_each_answer_maps_deterministically(
    question_id: str,
    answer_id: str,
    expected_bandwidth: str | None,
    expected_intent: str | None,
) -> None:
    """Every stable answer ID resolves its axis deterministically."""
    mode = resolve_quiz_answers({question_id: answer_id})
    if expected_bandwidth is not None:
        assert mode.bandwidth == expected_bandwidth
    if expected_intent is not None:
        assert mode.intent == expected_intent


def test_all_twelve_combinations_produce_valid_mode_state() -> None:
    """Every full quiz combination yields a valid bandwidth/intent session mode."""
    combinations = all_answer_combinations()
    assert len(combinations) == 3 * 4

    for answers in combinations:
        mode = resolve_quiz_answers(answers)
        assert mode.bandwidth in VALID_BANDWIDTHS
        assert mode.intent in VALID_INTENTS
        assert is_valid_reading_mode(mode.bandwidth, mode.intent)


def test_copy_is_separate_from_stable_values() -> None:
    """Reader-facing copy never leaks into the persisted contract values."""
    questions = list_quiz_questions()

    assert [q["id"] for q in questions] == [BANDWIDTH_QUESTION_ID, INTENT_QUESTION_ID]
    for question in questions:
        assert isinstance(question["prompt"], str) and question["prompt"]
        answers = question["answers"]
        assert isinstance(answers, list)
        for answer in answers:
            assert isinstance(answer, dict)
            assert set(answer.keys()) == {"id", "label"}
            label = answer["label"]
            assert isinstance(label, str) and label

    # Contract values come only from the closed value sets.
    for question in QUIZ_QUESTIONS:
        for answer in question.answers:
            assert answer.bandwidth in VALID_BANDWIDTHS or answer.bandwidth is None
            assert answer.intent in VALID_INTENTS or answer.intent is None


def test_unknown_question_raises() -> None:
    """An unknown question ID is rejected."""
    with pytest.raises(QuizResolutionError, match="Unknown quiz question"):
        resolve_quiz_answers({"vibes": "easy"})


def test_unknown_answer_raises() -> None:
    """An unknown answer ID is rejected."""
    with pytest.raises(QuizResolutionError, match="Unknown answer"):
        resolve_quiz_answers({BANDWIDTH_QUESTION_ID: "cosmic"})


def test_missing_axis_raises() -> None:
    """Answers that do not cover both axes are rejected."""
    with pytest.raises(QuizResolutionError, match="both bandwidth and intent"):
        resolve_quiz_answers({BANDWIDTH_QUESTION_ID: "easy"})


def test_schema_literals_match_contract_value_sets() -> None:
    """Schema Literal values stay synchronized with the contract constants."""
    from typing import get_args

    from app.schemas.session import SessionBandwidthValue, SessionIntentValue

    assert set(get_args(SessionBandwidthValue)) == set(VALID_BANDWIDTHS)
    assert set(get_args(SessionIntentValue)) == set(VALID_INTENTS)


def test_mode_update_request_requires_one_axis() -> None:
    """The canonical mode payload requires at least one axis and rejects extras."""
    with pytest.raises(ValidationError):
        SessionModeUpdateRequest(source="quiz")

    request = SessionModeUpdateRequest(bandwidth="light", intent="momentum")
    assert request.source == "quiz"

    with pytest.raises(ValidationError):
        SessionModeUpdateRequest(bandwidth="light", intent="momentum", source="quiz", vibe="extra")

    with pytest.raises(ValidationError):
        SessionModeUpdateRequest(bandwidth="spicy", intent="momentum")
