"""Tests for the reading-mode API.

These cover the acceptance contract for recording quiz/manual mode with the
correct source, confining results to the active session, and preserving the
prior mode on cancel/dismiss.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_quiz_results_recorded_with_source_quiz(auth_client) -> None:
    """Quiz answers must persist with source ``quiz`` and affect the active session."""
    response = await auth_client.post(
        "/api/v1/reading-mode",
        json={
            "answers": {"brainpower": "substantial", "pick": "explore"},
            "source": "quiz",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bandwidth"] == "deep"
    assert body["intent"] == "explore"
    assert body["source"] == "quiz"
    assert body["suggested"] is False


async def test_manual_mode_selector_entry_works(auth_client) -> None:
    """A direct manual entry must persist with source ``manual``."""
    response = await auth_client.post(
        "/api/v1/reading-mode",
        json={"bandwidth": "light", "intent": "momentum", "source": "manual"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bandwidth"] == "light"
    assert body["intent"] == "momentum"
    assert body["source"] == "manual"


async def test_get_returns_recorded_mode(auth_client) -> None:
    """The recorded mode must be retrievable and isolated to the active session."""
    await auth_client.post(
        "/api/v1/reading-mode",
        json={"answers": {"brainpower": "easy", "pick": "random"}, "source": "quiz"},
    )
    response = await auth_client.get("/api/v1/reading-mode")
    assert response.status_code == 200
    body = response.json()
    assert body["bandwidth"] == "light"
    assert body["intent"] == "random"
    assert body["source"] == "quiz"


async def test_requires_either_answers_or_resolved_mode(auth_client) -> None:
    """Submitting neither answers nor bandwidth/intent must fail validation."""
    response = await auth_client.post(
        "/api/v1/reading-mode", json={"source": "manual"}
    )
    assert response.status_code == 422


async def test_invalid_source_is_rejected(auth_client) -> None:
    response = await auth_client.post(
        "/api/v1/reading-mode",
        json={"bandwidth": "light", "intent": "momentum", "source": "forced-onboarding"},
    )
    assert response.status_code == 422


async def test_unknown_quiz_answer_is_rejected(auth_client) -> None:
    response = await auth_client.post(
        "/api/v1/reading-mode",
        json={"answers": {"brainpower": "unknown", "pick": "random"}, "source": "quiz"},
    )
    assert response.status_code == 422


async def test_dismiss_suggestion_leaves_prior_mode_intact(auth_client) -> None:
    """Dismissing a suggestion must not overwrite an existing mode."""
    await auth_client.post(
        "/api/v1/reading-mode",
        json={"bandwidth": "balanced", "intent": "familiar", "source": "manual"},
    )
    await auth_client.post("/api/v1/reading-mode/suggest")
    pre = await auth_client.get("/api/v1/reading-mode")
    assert pre.json()["suggested"] is True

    dismissed = await auth_client.post("/api/v1/reading-mode/dismiss-suggestion")
    assert dismissed.status_code == 200
    assert dismissed.json()["suggested"] is False
    assert dismissed.json()["bandwidth"] == "balanced"
    assert dismissed.json()["intent"] == "familiar"
    assert dismissed.json()["source"] == "manual"


async def test_suggest_marks_session_without_forcing(auth_client) -> None:
    """Suggesting the quiz must not set a mode or require the quiz before rolling."""
    suggested = await auth_client.post("/api/v1/reading-mode/suggest")
    assert suggested.status_code == 200
    assert suggested.json()["suggested"] is True
    assert suggested.json()["source"] is None

    current = await auth_client.get("/api/v1/reading-mode")
    assert current.json()["source"] is None
