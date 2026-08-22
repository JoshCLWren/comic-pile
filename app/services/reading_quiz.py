"""Two-question reading-mode quiz contract.

This module is the single source of truth for how the two-question reading-mode
quiz converts explicit reader answers into a deterministic session reading mode
(bandwidth + intent). It is intentionally free of UI and persistence concerns so
the mapping can be validated on the server and mirrored by the frontend.

Stable answer IDs are decoupled from the user-facing copy so wording can evolve
without changing the contract that persists on the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReadingBandwidth = Literal["light", "balanced", "deep"]
ReadingIntent = Literal["balanced", "momentum", "familiar", "explore", "random"]

VALID_BANDWIDTHS: frozenset[str] = frozenset({"light", "balanced", "deep"})
VALID_INTENTS: frozenset[str] = frozenset(
    {"balanced", "momentum", "familiar", "explore", "random"}
)

BANDWIDTH_QUESTION_ID = "brainpower"
INTENT_QUESTION_ID = "pick"


@dataclass(frozen=True)
class QuizAnswer:
    """One stable answer option inside a quiz question.

    Attributes:
        id: Stable identifier persisted across copy changes.
        label: Reader-facing copy for the answer.
        bandwidth: Bandwidth value selected by this answer, when the question
            targets the bandwidth axis.
        intent: Intent value selected by this answer, when the question targets
            the intent axis.
    """

    id: str
    label: str
    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None


@dataclass(frozen=True)
class QuizQuestion:
    """One quiz question with its stable answer options."""

    id: str
    prompt: str
    answers: tuple[QuizAnswer, ...]


@dataclass(frozen=True)
class ReadingMode:
    """Resolved reading mode produced by the quiz.

    Attributes:
        bandwidth: How much reading energy the reader has right now.
        intent: What kind of pick the reader wants next.
    """

    bandwidth: ReadingBandwidth
    intent: ReadingIntent


_BRAINPOWER_ANSWERS: tuple[QuizAnswer, ...] = (
    QuizAnswer(id="easy", label="Easy", bandwidth="light"),
    QuizAnswer(id="normal", label="Normal", bandwidth="balanced"),
    QuizAnswer(id="substantial", label="Give me something substantial", bandwidth="deep"),
)

_PICK_ANSWERS: tuple[QuizAnswer, ...] = (
    QuizAnswer(id="momentum", label="Keep something going", intent="momentum"),
    QuizAnswer(id="familiar", label="Something familiar", intent="familiar"),
    QuizAnswer(id="explore", label="Something different", intent="explore"),
    QuizAnswer(id="random", label="Don't overthink it", intent="random"),
)

QUIZ_QUESTIONS: tuple[QuizQuestion, ...] = (
    QuizQuestion(
        id=BANDWIDTH_QUESTION_ID,
        prompt="How much brain do you have right now?",
        answers=_BRAINPOWER_ANSWERS,
    ),
    QuizQuestion(
        id=INTENT_QUESTION_ID,
        prompt="What kind of pick sounds good?",
        answers=_PICK_ANSWERS,
    ),
)

_ANSWER_LOOKUP: dict[str, dict[str, QuizAnswer]] = {
    question.id: {answer.id: answer for answer in question.answers}
    for question in QUIZ_QUESTIONS
}


class QuizResolutionError(ValueError):
    """Raised when quiz answers cannot be resolved to a valid reading mode."""


def list_quiz_questions() -> list[dict[str, object]]:
    """Return the quiz questions with stable IDs and reader-facing copy.

    Returns:
        A JSON-serializable list of question dictionaries.
    """
    return [
        {
            "id": question.id,
            "prompt": question.prompt,
            "answers": [
                {"id": answer.id, "label": answer.label} for answer in question.answers
            ],
        }
        for question in QUIZ_QUESTIONS
    ]


def resolve_quiz_answers(answers: dict[str, str]) -> ReadingMode:
    """Resolve quiz answers into a deterministic reading mode.

    Every provided question ID must be a known question and every answer ID must
    be a known answer for that question. All valid combinations produce a valid
    ``ReadingMode`` because each question contributes exactly one axis.

    Args:
        answers: Mapping of question ID to the selected answer ID.

    Returns:
        The resolved :class:`ReadingMode`.

    Raises:
        QuizResolutionError: If a question or answer ID is unknown, or both
            axes were not resolved.
    """
    if not isinstance(answers, dict):
        raise QuizResolutionError("Quiz answers must be a mapping of question ID to answer ID")

    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None

    for question_id, answer_id in answers.items():
        question_lookup = _ANSWER_LOOKUP.get(str(question_id))
        if question_lookup is None:
            raise QuizResolutionError(f"Unknown quiz question: {question_id!r}")
        answer = question_lookup.get(str(answer_id))
        if answer is None:
            raise QuizResolutionError(f"Unknown answer {answer_id!r} for question {question_id!r}")
        if answer.bandwidth is not None:
            bandwidth = answer.bandwidth
        if answer.intent is not None:
            intent = answer.intent

    if bandwidth is None or intent is None:
        raise QuizResolutionError("Quiz answers must resolve both bandwidth and intent")

    return ReadingMode(bandwidth=bandwidth, intent=intent)


def all_answer_combinations() -> list[dict[str, str]]:
    """Enumerate every valid fully-specified answer combination.

    Returns:
        One answer mapping per combination, useful for exhaustive coverage.
    """
    return [
        {BANDWIDTH_QUESTION_ID: bandwidth_answer.id, INTENT_QUESTION_ID: pick_answer.id}
        for bandwidth_answer in _BRAINPOWER_ANSWERS
        for pick_answer in _PICK_ANSWERS
    ]


def is_valid_reading_mode(bandwidth: str, intent: str) -> bool:
    """Return True when the bandwidth/intent pair is a valid reading mode."""
    return bandwidth in VALID_BANDWIDTHS and intent in VALID_INTENTS
