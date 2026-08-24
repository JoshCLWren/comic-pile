"""Pure shared contract for the optional two-question reading-mode quiz.

This module is intentionally dependency-free (no SQLAlchemy, no FastAPI, no I/O)
so the same deterministic mapping can be unit tested in isolation and reused by
both the backend session-mode API and the frontend quiz UI without duplicating
the answer-to-mode logic in component conditionals.

See issue #1735 (Phase 6 of #1685).

Contract rules
--------------
- Stable answer IDs map deterministically to a bandwidth and/or intent value.
- Quiz copy (wording) lives on the option objects, fully separate from the
  stable answer IDs, so wording can evolve without changing IDs or mappings.
- All valid combinations of one bandwidth answer and one intent answer produce
  a valid :class:`SessionReadingMode`.
- A resolved quiz result is tagged with source ``quiz`` and is meant to apply
  only to the current session; this module does not persist anything.
- No creator/Taste Bank logic is included here.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class ReadingBandwidth(StrEnum):
    """Mental demand the reader has capacity for right now."""

    LIGHT = "light"
    BALANCED = "balanced"
    DEEP = "deep"


class ReadingIntent(StrEnum):
    """What kind of pick the reader wants right now."""

    BALANCED = "balanced"
    MOMENTUM = "momentum"
    FAMILIAR = "familiar"
    EXPLORE = "explore"
    RANDOM = "random"


class ReadingModeSource(StrEnum):
    """How a session reading mode was chosen."""

    DEFAULT = "default"
    INFERRED = "inferred"
    MANUAL = "manual"
    QUIZ = "quiz"


@dataclass(frozen=True)
class SessionReadingMode:
    """A resolved reading mode for the current session.

    Both ``bandwidth`` and ``intent`` are validated enums, so constructing an
    instance with an out-of-range value fails fast. The ``source`` records how
    the mode was decided; quiz results always use ``ReadingModeSource.QUIZ``.
    """

    bandwidth: ReadingBandwidth
    intent: ReadingIntent
    source: ReadingModeSource = ReadingModeSource.DEFAULT


@dataclass(frozen=True)
class QuizAnswerOption:
    """One selectable answer in the quiz.

    ``id`` is the stable key used by the mapping logic and persisted nowhere
    meaningful; ``copy`` is the human-facing wording and may change freely.
    Exactly one of ``bandwidth``/``intent`` is set per question's options.
    """

    id: str
    copy: str
    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None


@dataclass(frozen=True)
class QuizQuestion:
    """One quiz question with its stable id, wording, and answer options."""

    id: str
    prompt: str
    options: tuple[QuizAnswerOption, ...]


@dataclass(frozen=True)
class ReadingModeQuiz:
    """The canonical two-question reading-mode quiz definition."""

    id: str
    title: str
    questions: tuple[QuizQuestion, ...]


# Stable answer IDs. These are the only keys the resolver understands and must
# never be reused or renamed; only ``copy``/``prompt`` wording may evolve.
BANDWIDTH_QUESTION_ID = "bandwidth"
INTENT_QUESTION_ID = "intent"

_READING_MODE_QUIZ = ReadingModeQuiz(
    id="reading-mode-v1",
    title="Reading mode",
    questions=(
        QuizQuestion(
            id=BANDWIDTH_QUESTION_ID,
            prompt="How much brain do you have right now?",
            options=(
                QuizAnswerOption(id="light", copy="Easy", bandwidth=ReadingBandwidth.LIGHT),
                QuizAnswerOption(
                    id="balanced", copy="Normal", bandwidth=ReadingBandwidth.BALANCED
                ),
                QuizAnswerOption(
                    id="deep",
                    copy="Give me something substantial",
                    bandwidth=ReadingBandwidth.DEEP,
                ),
            ),
        ),
        QuizQuestion(
            id=INTENT_QUESTION_ID,
            prompt="What kind of pick sounds good?",
            options=(
                QuizAnswerOption(
                    id="momentum", copy="Keep something going", intent=ReadingIntent.MOMENTUM
                ),
                QuizAnswerOption(
                    id="familiar", copy="Something familiar", intent=ReadingIntent.FAMILIAR
                ),
                QuizAnswerOption(
                    id="explore", copy="Something different", intent=ReadingIntent.EXPLORE
                ),
                QuizAnswerOption(
                    id="random", copy="Don't overthink it", intent=ReadingIntent.RANDOM
                ),
            ),
        ),
    ),
)


def get_reading_mode_quiz() -> ReadingModeQuiz:
    """Return the canonical reading-mode quiz definition.

    Returns:
        The immutable :class:`ReadingModeQuiz` used by the UI and resolver.
    """
    return _READING_MODE_QUIZ


def _find_option(question: QuizQuestion, answer_id: str) -> QuizAnswerOption | None:
    """Return the option with the given stable id, or ``None``.

    Args:
        question: The question to search.
        answer_id: The stable answer id selected by the reader.

    Returns:
        The matching :class:`QuizAnswerOption`, or ``None`` if not present.
    """
    for option in question.options:
        if option.id == answer_id:
            return option
    return None


def resolve_quiz_answers(answers: Mapping[str, str]) -> SessionReadingMode:
    """Convert explicit quiz answers into a session reading mode.

    Only the stable answer IDs in ``answers`` are read; the option copy is
    ignored. Every supported combination of one bandwidth answer and one intent
    answer yields a valid :class:`SessionReadingMode` tagged with source
    ``quiz``.

    Args:
        answers: Mapping of stable question id to stable answer id, e.g.
            ``{"bandwidth": "light", "intent": "momentum"}``.

    Returns:
        A :class:`SessionReadingMode` with ``source`` set to
        :attr:`ReadingModeSource.QUIZ`.

    Raises:
        ValueError: If an unknown answer id is supplied, or if the answers do
            not resolve to both a bandwidth and an intent.
    """
    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None

    for question in _READING_MODE_QUIZ.questions:
        answer_id = answers.get(question.id)
        if answer_id is None:
            continue
        option = _find_option(question, answer_id)
        if option is None:
            raise ValueError(
                f"Unknown answer '{answer_id}' for question '{question.id}'"
            )
        if option.bandwidth is not None:
            bandwidth = option.bandwidth
        if option.intent is not None:
            intent = option.intent

    if bandwidth is None or intent is None:
        raise ValueError(
            "Reading-mode quiz requires both a bandwidth and an intent answer"
        )

    return SessionReadingMode(
        bandwidth=bandwidth,
        intent=intent,
        source=ReadingModeSource.QUIZ,
    )


__all__ = [
    "BANDWIDTH_QUESTION_ID",
    "INTENT_QUESTION_ID",
    "ReadingBandwidth",
    "ReadingIntent",
    "ReadingModeSource",
    "ReadingModeQuiz",
    "QuizAnswerOption",
    "QuizQuestion",
    "SessionReadingMode",
    "get_reading_mode_quiz",
    "resolve_quiz_answers",
]
