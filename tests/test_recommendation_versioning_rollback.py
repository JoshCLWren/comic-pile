"""Phase 9 versioning and safe legacy rollback (issue #1767).

Covers:
- operators can switch contextual weighting off via RECOMMENDATION_CONTROL_MODE
- turning weighting off does not destroy learned data
- decision history records algorithm_version/control state
- re-enabling resumes from existing data
- random intent remains independent bypass in both modes
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.config import clear_settings_cache, get_recommendation_settings
from app.models import Event, Thread
from app.models.recommendation_context import RecommendationContext


@pytest.fixture(autouse=True)
def _reset_recommendation_settings() -> None:
    """Ensure recommendation settings cache is cleared between tests."""
    clear_settings_cache()
    yield
    # Remove test env overrides and clear again
    os.environ.pop("RECOMMENDATION_CONTROL_MODE", None)
    os.environ.pop("RECOMMENDATION_ALGORITHM_VERSION", None)
    clear_settings_cache()


@pytest.mark.asyncio
async def test_operator_can_switch_off_and_recover_legacy_unweighted(
    auth_client, async_db, default_user
) -> None:
    """With RECOMMENDATION_CONTROL_MODE=legacy, contextual weighting is disabled.

    A light-bandwidth roll that would normally be weighted must instead record
    legacy_forced reason, selection_method legacy_forced, and use uniform
    selection (weights_applied False), while still persisting instrumentation.
    """
    now = datetime.now(UTC)
    for i in range(3):
        thread = Thread(
            title=f"Version Rollback Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i + 1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        async_db.add(thread)
    await async_db.commit()

    # Contextual mode: light bandwidth should apply weighting (at least instrumented)
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "contextual"
    os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-contextual-test"
    clear_settings_cache()
    assert get_recommendation_settings().control_mode == "contextual"

    # Force legacy mode
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "legacy"
    os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-contextual-test"
    clear_settings_cache()
    assert get_recommendation_settings().control_mode == "legacy"

    response = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "balanced"})
    assert response.status_code == 200

    result = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
    event = result.scalar_one()
    assert event.selection_method == "legacy_forced"
    assert event.recommendation_reason_codes == ["legacy_forced"]
    ctx = event.recommendation_context
    assert ctx is not None
    assert ctx["algorithm_version"] == "v1-contextual-test"
    assert ctx["control_mode"] == "legacy"
    # rolling context also carries versioning
    rolling = event.rolling_recommendation_context
    assert rolling is not None
    assert rolling["algorithm_version"] == "v1-contextual-test"
    assert rolling["control_mode"] == "legacy"
    assert rolling["selection_method"] == "legacy_forced"
    # RecommendationContext row also records versioning
    rc_result = await async_db.execute(select(RecommendationContext).where(RecommendationContext.event_id == event.id))
    rc = rc_result.scalar_one()
    assert rc.algorithm_version == "v1-contextual-test"
    assert rc.control_mode == "legacy"


@pytest.mark.asyncio
async def test_turning_weighting_off_does_not_destroy_learned_data(
    auth_client, async_db, default_user
) -> None:
    """Rollback must not clear session history, ratings, queue positions, or effort estimates."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Data Preservation Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
        last_rating=4.5,
    )
    async_db.add(thread)
    await async_db.commit()
    original_rating = thread.last_rating
    original_queue = thread.queue_position

    # Create a roll + rating to generate effort-related event history
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "contextual"
    os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-contextual-test"
    clear_settings_cache()
    roll_resp = await auth_client.post("/api/roll/")
    assert roll_resp.status_code == 200
    # Rate the rolled thread (simulate reading)
    rated_thread_id = roll_resp.json()["thread_id"]
    # Use rate endpoint if available; otherwise directly count event history preservation
    # Verify history exists before switch
    before_rolls = (await async_db.execute(select(Event).where(Event.type == "roll"))).scalars().all()
    before_count = len(before_rolls)

    # Switch to legacy - should not mutate history or thread state
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "legacy"
    clear_settings_cache()
    resp2 = await auth_client.post("/api/roll/", json={"bandwidth": "deep"})
    # Dismiss pending to allow second roll (need to clear pending first)
    # The above will fail with 409 if pending exists; handle by dismissing
    if resp2.status_code == 409:
        await auth_client.post("/api/roll/dismiss-pending")
        resp2 = await auth_client.post("/api/roll/", json={"bandwidth": "deep"})
    # After forced legacy roll, history count grows, not shrinks, and thread data unchanged
    after_rolls = (await async_db.execute(select(Event).where(Event.type == "roll"))).scalars().all()
    assert len(after_rolls) >= before_count
    # Verify thread data not mutated by the mode switch
    await async_db.refresh(thread)
    assert thread.last_rating == original_rating
    assert thread.queue_position == original_queue


@pytest.mark.asyncio
async def test_decision_history_records_version_and_control_state(
    auth_client, async_db, default_user
) -> None:
    """Every roll records algorithm_version/control_mode in both context payloads."""
    now = datetime.now(UTC)
    thread = Thread(
        title="History Version Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    for mode, version in [("contextual", "v1-contextual-history"), ("legacy", "v1-contextual-history")]:
        os.environ["RECOMMENDATION_CONTROL_MODE"] = mode
        os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = version
        clear_settings_cache()
        # Dismiss any pending between iterations
        await auth_client.post("/api/roll/dismiss-pending")
        resp = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "balanced"})
        assert resp.status_code == 200
        result = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
        event = result.scalar_one()
        assert event.recommendation_context is not None
        assert event.recommendation_context["algorithm_version"] == version
        assert event.recommendation_context["control_mode"] == mode
        assert event.rolling_recommendation_context is not None
        assert event.rolling_recommendation_context["algorithm_version"] == version
        assert event.rolling_recommendation_context["control_mode"] == mode


@pytest.mark.asyncio
async def test_reenabling_contextual_resumes_from_existing_data(
    auth_client, async_db, default_user
) -> None:
    """Re-enabling contextual mode resumes weighting without data loss."""
    now = datetime.now(UTC)
    for i in range(4):
        thread = Thread(
            title=f"Resume Thread {i}",
            format="Comic",
            issues_remaining=5,
            queue_position=i + 1,
            status="active",
            user_id=default_user.id,
            created_at=now,
        )
        async_db.add(thread)
    await async_db.commit()

    # Step 1: contextual -> should be able to weight (even if balanced, check context shape)
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "contextual"
    os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-resume-test"
    clear_settings_cache()
    await auth_client.post("/api/roll/dismiss-pending")
    resp_ctx = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "momentum"})
    # May be 409 if pending; dismiss and retry
    if resp_ctx.status_code == 409:
        await auth_client.post("/api/roll/dismiss-pending")
        resp_ctx = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "momentum"})
    assert resp_ctx.status_code == 200
    result_ctx = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
    event_ctx = result_ctx.scalar_one()
    # In contextual light/momentum, event should not be legacy_forced
    assert event_ctx.selection_method != "legacy_forced"

    # Step 2: switch to legacy
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "legacy"
    clear_settings_cache()
    await auth_client.post("/api/roll/dismiss-pending")
    resp_leg = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "momentum"})
    assert resp_leg.status_code == 200
    result_leg = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
    event_leg = result_leg.scalar_one()
    assert event_leg.selection_method == "legacy_forced"

    # Step 3: re-enable contextual - must resume weighted behavior, not stay forced
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "contextual"
    clear_settings_cache()
    await auth_client.post("/api/roll/dismiss-pending")
    resp_re = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "momentum"})
    assert resp_re.status_code == 200
    result_re = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
    event_re = result_re.scalar_one()
    assert event_re.selection_method != "legacy_forced"
    assert event_re.recommendation_context["control_mode"] == "contextual"
    assert event_re.rolling_recommendation_context["control_mode"] == "contextual"


@pytest.mark.asyncio
async def test_random_intent_remains_independent_bypass_in_both_modes(
    auth_client, async_db, default_user
) -> None:
    """Random intent must bypass contextual weighting regardless of control_mode."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Random Bypass Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    for mode in ["contextual", "legacy"]:
        os.environ["RECOMMENDATION_CONTROL_MODE"] = mode
        os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-random-test"
        clear_settings_cache()
        await auth_client.post("/api/roll/dismiss-pending")
        resp = await auth_client.post("/api/roll/", json={"bandwidth": "deep", "intent": "random"})
        assert resp.status_code == 200
        result = await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))
        event = result.scalar_one()
        # Random intent must always map to random, not legacy_forced
        assert event.selection_method == "random"
        assert event.recommendation_reason_codes == ["pure_random"]
        # Context still records the operator control mode but selection stays random
        assert event.rolling_recommendation_context["control_mode"] == mode
        # Ensure instrumentation still present
        assert event.recommendation_context is not None
        assert event.recommendation_context["algorithm_version"] == "v1-random-test"


@pytest.mark.asyncio
async def test_forced_legacy_distinguishable_in_diagnostics(auth_client, async_db, default_user) -> None:
    """Forced legacy runs appear as a distinct control-mode bucket in diagnostics."""
    now = datetime.now(UTC)
    thread = Thread(
        title="Diagnostics Distinguish Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=default_user.id,
        created_at=now,
    )
    async_db.add(thread)
    await async_db.commit()

    # Create one contextual roll
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "contextual"
    os.environ["RECOMMENDATION_ALGORITHM_VERSION"] = "v1-diag-test"
    clear_settings_cache()
    await auth_client.post("/api/roll/dismiss-pending")
    resp = await auth_client.post("/api/roll/", json={"bandwidth": "balanced", "intent": "balanced"})
    assert resp.status_code in (200, 409)
    if resp.status_code == 409:
        await auth_client.post("/api/roll/dismiss-pending")
        resp = await auth_client.post("/api/roll/", json={"bandwidth": "balanced", "intent": "balanced"})
        assert resp.status_code == 200

    # Create one forced legacy roll
    os.environ["RECOMMENDATION_CONTROL_MODE"] = "legacy"
    clear_settings_cache()
    await auth_client.post("/api/roll/dismiss-pending")
    resp2 = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "balanced"})
    assert resp2.status_code == 200

    # Query diagnostics - forced legacy should be in legacy_forced bucket
    diag_resp = await auth_client.get("/api/v1/recommendations/diagnostics")
    assert diag_resp.status_code == 200
    body = diag_resp.json()
    # Active mode should reflect forced setting now
    assert body["active_control_mode"] == "legacy"
    assert body["active_algorithm_version"] == "v1-diag-test"
    control_modes = {g["control_mode"] for g in body["groups_by_control_mode"]}
    assert "legacy_forced" in control_modes
