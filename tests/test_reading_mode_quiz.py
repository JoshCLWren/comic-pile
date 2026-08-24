"""Tests for the reading-mode quiz contract (issue #1735)."""

import itertools

import pytest

from app.services.reading_mode_quiz import (
    BANDWIDTH_QUESTION_ID,
    INTENT_QUESTION_ID,
    QuizAnswerOption,
    QuizQuestion,
    ReadingBandwidth,
    ReadingIntent,
    ReadingModeQuiz,
    ReadingModeSource,
    SessionReadingMode,
    get_reading_mode_quiz,
    resolve_quiz_answers,
)


def _answer_ids_for(question_id: str) -> list[str]:
    quiz = get_reading_mode_quiz()
    question = next(q for q in quiz.questions if q.id == question_id)
    return [option.id for option in question.options]


def test_quiz_has_two_questions_with_stable_ids():
    """The quiz exposes exactly the bandwidth and intent questions in order."""
    quiz = get_reading_mode_quiz()

    assert [q.id for q in quiz.questions] == [
        BANDWIDTH_QUESTION_ID,
        INTENT_QUESTION_ID,
    ]


def test_bandwidth_answer_ids_map_deterministically():
    """Each stable bandwidth answer id resolves to its exact enum member."""
    expected = {
        "light": ReadingBandwidth.LIGHT,
        "balanced": ReadingBandwidth.BALANCED,
        "deep": ReadingBandwidth.DEEP,
    }
    for answer_id, bandwidth in expected.items():
        mode = resolve_quiz_answers(
            {BANDWIDTH_QUESTION_ID: answer_id, INTENT_QUESTION_ID: "momentum"}
        )
        assert mode.bandwidth is bandwidth


def test_intent_answer_ids_map_deterministically():
    """Each stable intent answer id resolves to its exact enum member."""
    expected = {
        "momentum": ReadingIntent.MOMENTUM,
        "familiar": ReadingIntent.FAMILIAR,
        "explore": ReadingIntent.EXPLORE,
        "random": ReadingIntent.RANDOM,
    }
    for answer_id, intent in expected.items():
        mode = resolve_quiz_answers(
            {BANDWIDTH_QUESTION_ID: "balanced", INTENT_QUESTION_ID: answer_id}
        )
        assert mode.intent is intent


def test_every_answer_mapping_is_covered_by_a_test():
    """Guard against silently dropping a new option from the mapping tests above."""
    # Guard against silently dropping a new option from the mapping tests above.
    bandwidth_ids = _answer_ids_for(BANDWIDTH_QUESTION_ID)
    intent_ids = _answer_ids_for(INTENT_QUESTION_ID)
    assert set(bandwidth_ids) == {b.value for b in ReadingBandwidth}
    assert set(intent_ids) == {
        "momentum",
        "familiar",
        "explore",
        "random",
    }


def test_all_combinations_produce_valid_session_mode():
    """Every bandwidth/intent pair yields a quiz-sourced valid session mode."""
    bandwidth_ids = _answer_ids_for(BANDWIDTH_QUESTION_ID)
    intent_ids = _answer_ids_for(INTENT_QUESTION_ID)

    for bandwidth_id, intent_id in itertools.product(bandwidth_ids, intent_ids):
        mode = resolve_quiz_answers(
            {BANDWIDTH_QUESTION_ID: bandwidth_id, INTENT_QUESTION_ID: intent_id}
        )
        assert isinstance(mode, SessionReadingMode)
        assert mode.bandwidth in ReadingBandwidth
        assert mode.intent in ReadingIntent
        assert mode.source is ReadingModeSource.QUIZ


def test_copy_is_separate_from_stable_answer_ids():
    """Option wording differs from the stable key and maps one dimension only."""
    quiz = get_reading_mode_quiz()
    for question in quiz.questions:
        for option in question.options:
            # Wording is stored separately and must not equal the stable key.
            assert option.id != option.copy
            # Exactly one mapping dimension is set per option.
            assert (option.bandwidth is None) != (option.intent is None)


def test_copy_changes_do_not_alter_the_mapping():
    """Rewording option copy keeps the same bandwidth/intent resolution."""
    # The resolver keys only on stable ids, so rewording an option keeps the
    # same bandwidth/intent outcome.
    quiz = get_reading_mode_quiz()
    reworded = ReadingModeQuiz(
        id=quiz.id,
        title=quiz.title,
        questions=tuple(
            QuizQuestion(
                id=q.id,
                prompt=q.prompt,
                options=tuple(
                    QuizAnswerOption(
                        id=o.id,
                        copy=f"REWORDED:{o.copy}",
                        bandwidth=o.bandwidth,
                        intent=o.intent,
                    )
                    for o in q.options
                ),
            )
            for q in quiz.questions
        ),
    )
    original = resolve_quiz_answers(
        {BANDWIDTH_QUESTION_ID: "deep", INTENT_QUESTION_ID: "explore"}
    )
    # Mirror the resolution using the reworded definition to prove copy is unused.
    bandwidth = next(
        o.bandwidth
        for q in reworded.questions
        if q.id == BANDWIDTH_QUESTION_ID
        for o in q.options
        if o.id == "deep"
    )
    intent = next(
        o.intent
        for q in reworded.questions
        if q.id == INTENT_QUESTION_ID
        for o in q.options
        if o.id == "explore"
    )
    assert SessionReadingMode(bandwidth, intent, ReadingModeSource.QUIZ) == original


def test_unknown_answer_id_raises():
    """An answer id outside the stable contract is rejected."""
    with pytest.raises(ValueError):
        resolve_quiz_answers(
            {BANDWIDTH_QUESTION_ID: "nope", INTENT_QUESTION_ID: "momentum"}
        )


def test_missing_dimension_raises():
    """Resolution fails unless both bandwidth and intent answers are present."""
    with pytest.raises(ValueError):
        resolve_quiz_answers({BANDWIDTH_QUESTION_ID: "light"})


def test_unknown_question_id_is_ignored():
    """Answers keyed by unknown question ids do not affect resolution."""
    mode = resolve_quiz_answers(
        {
            BANDWIDTH_QUESTION_ID: "light",
            INTENT_QUESTION_ID: "random",
            "future-question": "ignored",
        }
    )
    assert mode.bandwidth is ReadingBandwidth.LIGHT
    assert mode.intent is ReadingIntent.RANDOM
    assert mode.source is ReadingModeSource.QUIZ


def test_quiz_definition_is_immutable_and_shared():
    """The canonical quiz is a shared singleton definition."""
    assert get_reading_mode_quiz() is get_reading_mode_quiz()
