"""Reading-mode quiz contract.

This module is the single source of truth for how the two-question reading-mode
quiz converts explicit answers into a deterministic session ``ReadingMode``
(bandwidth + intent). It is intentionally free of UI and persistence concerns so
that both the frontend and the backend share one stable mapping.

Stable answer IDs are decoupled from the user-facing copy so wording can evolve
without changing the contract that persists on the session.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ReadingBandwidth = Literal["light", "balanced", "deep"]
ReadingIntent = Literal["momentum", "familiar", "explore", "random"]

VALID_BANDWIDTHS: frozenset[str] = frozenset({"light", "balanced", "deep"})
VALID_INTENTS: frozenset[str] = frozenset({"momentum", "familiar", "explore", "random"})


class ReadingModeSource(StrEnum):
    """Origin of a session reading-mode setting.

    ``quiz`` results are produced by the two-question quiz. ``manual`` results
    are produced by a direct mode-selector entry. Both apply only to the active
    session.
    """

    QUIZ = "quiz"
    MANUAL = "manual"

    @classmethod
    def values(cls) -> frozenset[str]:
        """Return the set of valid source string values."""
        return frozenset(member.value for member in cls)


@dataclass(frozen=True)
class QuizAnswer:
    """A single stable answer option within a quiz question."""

    id: str
    label: str
    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None

    def to_dict(self) -> dict[str, str | None]:
        """Serialize the answer to a JSON-safe dictionary."""
        return {
            "id": self.id,
            "label": self.label,
            "bandwidth": self.bandwidth,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class QuizQuestion:
    """A single quiz question with stable answer options."""

    id: str
    prompt: str
    answers: list[QuizAnswer]

    def to_dict(self) -> dict[str, object]:
        """Serialize the question to a JSON-safe dictionary."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "answers": [answer.to_dict() for answer in self.answers],
        }


@dataclass(frozen=True)
class ReadingMode:
    """Resolved reading mode produced by the quiz.

    Attributes:
        bandwidth: How much reading energy the reader has (light/balanced/deep).
        intent: What kind of pick the reader wants.
    """

    bandwidth: ReadingBandwidth
    intent: ReadingIntent

    def to_dict(self) -> dict[str, str]:
        """Serialize the reading mode to a JSON-safe dictionary."""
        return {"bandwidth": self.bandwidth, "intent": self.intent}


_BRAINPOWER_ANSWERS: list[QuizAnswer] = [
    QuizAnswer(id="easy", label="Easy", bandwidth="light"),
    QuizAnswer(id="normal", label="Normal", bandwidth="balanced"),
    QuizAnswer(id="substantial", label="Give me something substantial", bandwidth="deep"),
]

_PICK_ANSWERS: list[QuizAnswer] = [
    QuizAnswer(id="momentum", label="Keep something going", intent="momentum"),
    QuizAnswer(id="familiar", label="Something familiar", intent="familiar"),
    QuizAnswer(id="explore", label="Something different", intent="explore"),
    QuizAnswer(id="random", label="Don't overthink it", intent="random"),
]

QUIZ_QUESTIONS: list[QuizQuestion] = [
    QuizQuestion(
        id="brainpower",
        prompt="How much brain do you have right now?",
        answers=_BRAINPOWER_ANSWERS,
    ),
    QuizQuestion(
        id="pick",
        prompt="What kind of pick sounds good?",
        answers=_PICK_ANSWERS,
    ),
]

_ANSWER_LOOKUP: dict[str, dict[str, QuizAnswer]] = {
    question.id: {answer.id: answer for answer in question.answers}
    for question in QUIZ_QUESTIONS
}


class QuizResolutionError(ValueError):
    """Raised when quiz answers cannot be resolved to a valid reading mode."""


def list_quiz_questions() -> list[dict[str, object]]:
    """Return the quiz questions with stable IDs and copy.

    Returns:
        A list of JSON-serializable question dictionaries.
    """
    return [question.to_dict() for question in QUIZ_QUESTIONS]


def resolve_quiz_answers(answers: dict[str, str]) -> ReadingMode:
    """Resolve quiz answers into a deterministic reading mode.

    Every provided question ID must be a known question and every answer ID must
    be a known answer for that question. All valid combinations produce a valid
    ``ReadingMode`` because each answer contributes exactly one bandwidth or
    intent axis.

    Args:
        answers: Mapping of question ID to selected answer ID.

    Returns:
        The resolved ``ReadingMode``.

    Raises:
        QuizResolutionError: If a question or answer ID is unknown.
    """
    if not isinstance(answers, dict):
        raise QuizResolutionError("Quiz answers must be a mapping of question ID to answer ID")

    bandwidth: ReadingBandwidth | None = None
    intent: ReadingIntent | None = None

    for question_id, answer_id in answers.items():
        question_lookup = _ANSWER_LOOKUP.get(question_id)
        if question_lookup is None:
            raise QuizResolutionError(f"Unknown quiz question: {question_id!r}")
        answer = question_lookup.get(answer_id)
        if answer is None:
            raise QuizResolutionError(
                f"Unknown answer {answer_id!r} for question {question_id!r}"
            )
        if answer.bandwidth is not None:
            bandwidth = answer.bandwidth
        if answer.intent is not None:
            intent = answer.intent

    if bandwidth is None or intent is None:
        raise QuizResolutionError("Quiz answers did not resolve both bandwidth and intent")

    return ReadingMode(bandwidth=bandwidth, intent=intent)


def all_answer_combinations() -> list[dict[str, str]]:
    """Enumerate every valid question/answer combination.

    Returns:
        A list of answer mappings, one per fully-specified combination, useful
        for exhaustive acceptance coverage.
    """
    combinations: list[dict[str, str]] = []
    for brainpower in _BRAINPOWER_ANSWERS:
        for pick in _PICK_ANSWERS:
            combinations.append({"brainpower": brainpower.id, "pick": pick.id})
    return combinations


def is_valid_reading_mode(bandwidth: str, intent: str) -> bool:
    """Return True when the bandwidth/intent pair is a valid reading mode."""
    return bandwidth in VALID_BANDWIDTHS and intent in VALID_INTENTS
