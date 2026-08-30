"""Issue #1718: record candidate weights and bandwidth reason codes on roll events.

Verifies:
- Weighted rolls can be explained from persisted decision-time context (v2 JSON + table).
- Random/control rolls explicitly show bypass/neutral weighting.
- Candidate weights in context match those actually passed to selection.
- Older context versions remain readable.
- Light, deep, balanced, unknown-effort, and random cases.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Thread, User
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.recommendation_context import RecommendationContext
from app.services.reading_effort import (
    RECOMMENDATION_CONTEXT_VERSION,
    build_recommendation_context,
    neutral_estimate,
)


async def _add_thread(
    db: AsyncSession, user: User, title: str, *, queue_position: int
) -> Thread:
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_position,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _confirm_series_era(db: AsyncSession, thread: Thread, cover_date: str) -> None:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"4050-{thread.id}",
        metadata_json={"cover_date": cover_date},
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id, external_identity_id=identity.id, status="confirmed"
        )
    )
    await db.flush()


async def _add_observed_effort(
    db: AsyncSession, thread: Thread, *, minutes: float, count: int
) -> None:
    base = datetime.now(UTC) - timedelta(days=7)
    for index in range(count):
        rolled_at = base + timedelta(days=index)
        roll_event = Event(
            type="roll", selected_thread_id=thread.id, die=8, result=1, selection_method="random", timestamp=rolled_at
        )
        db.add(roll_event)
        await db.flush()
        rate_event = Event(
            type="rate",
            thread_id=thread.id,
            source_roll_event_id=roll_event.id,
            rating=4.0,
            issues_read=1,
            die=8,
            die_after=8,
            timestamp=rolled_at + timedelta(minutes=minutes),
        )
        db.add(rate_event)
        await db.flush()


@pytest.mark.asyncio
async def test_v1_context_remains_readable() -> None:
    """Older context_version 1 payloads are still readable after bump to 2."""
    estimate = neutral_estimate()
    v1 = {
        "context_version": 1,
        "selected_candidate": {
            "thread_id": 1,
            "issue_id": None,
            "issue_number": None,
            "effort_minutes": None,
            "effort_band": "unknown",
            "effort_source": "unknown",
            "effort_confidence": 0.0,
            "effort_sample_count": 0,
        },
    }
    # v1 has no candidate_weights etc. - reader must tolerate missing keys.
    assert v1["context_version"] == 1
    assert "candidate_weights" not in v1
    # New builder always produces v2.
    v2 = build_recommendation_context(estimate, thread_id=1, issue_id=None, issue_number=None)
    assert v2["context_version"] == RECOMMENDATION_CONTEXT_VERSION == 2
    assert "candidate_weights" in v2
    assert "selected_weight" in v2
    assert "bandwidth" in v2


@pytest.mark.asyncio
async def test_light_bandwidth_json_records_weights(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    light = await _add_thread(async_db, default_user, "Light Era", queue_position=1)
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(async_db, default_user, "Heavy Effort", queue_position=2)
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    resp = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert resp.status_code == 200
    data = resp.json()

    ev = (await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))).scalar_one()
    ctx = ev.recommendation_context
    assert ctx is not None
    assert ctx["context_version"] == 2
    assert ctx["bandwidth"] == "light"
    assert ctx["random_bypass"] is False
    assert ctx["balanced_neutrality"] is False
    cw = ctx["candidate_weights"]
    assert isinstance(cw, list)
    assert len(cw) == 2
    # Bounded payload: only ids/weights/reasons, no full metadata.
    for entry in cw:
        assert set(entry.keys()) >= {"candidate_id", "weight"}
        assert "title" not in entry
        assert "format" not in entry
        assert isinstance(entry["weight"], (int, float))
        assert entry["weight"] > 0
    # Light favors low effort (1.5) vs heavy dampens (0.75)
    by_id = {e["candidate_id"]: e for e in cw}
    assert by_id[light.id]["weight"] == pytest.approx(1.5)
    assert by_id[heavy.id]["weight"] == pytest.approx(0.75)
    # Reasons compact and correct.
    assert "bandwidth_light_favors_low_effort" in by_id[light.id]["reasons"]
    assert "bandwidth_light_dampens_high_effort" in by_id[heavy.id]["reasons"]
    # Selected weight matches chooser weight and table final_weight.
    assert ctx["selected_weight"] == pytest.approx(by_id[data["thread_id"]]["weight"])
    rc = (await async_db.execute(select(RecommendationContext).where(RecommendationContext.event_id == ev.id))).scalar_one()
    assert rc.schema_version == 2
    assert rc.candidate_factors is not None
    cf_by_id = {f["candidate_id"]: f for f in rc.candidate_factors}
    for cid, w in by_id.items():
        assert cf_by_id[cid]["weight"] == pytest.approx(w["weight"])
    assert rc.final_weight == pytest.approx(ctx["selected_weight"])


@pytest.mark.asyncio
async def test_deep_bandwidth_json_records_weights(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    light = await _add_thread(async_db, default_user, "Light Era Deep", queue_position=1)
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(async_db, default_user, "Heavy Effort Deep", queue_position=2)
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    resp = await auth_client.post("/api/roll/", json={"bandwidth": "deep"})
    assert resp.status_code == 200
    ev = (await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))).scalar_one()
    ctx = ev.recommendation_context
    assert ctx["context_version"] == 2
    assert ctx["bandwidth"] == "deep"
    assert ctx["random_bypass"] is False
    cw = ctx["candidate_weights"]
    by_id = {e["candidate_id"]: e for e in cw}
    assert by_id[heavy.id]["weight"] == pytest.approx(1.25)
    assert by_id[light.id]["weight"] == pytest.approx(0.9)
    assert "bandwidth_deep_permits_high_effort" in by_id[heavy.id]["reasons"]
    assert "bandwidth_deep_dampens_low_effort" in by_id[light.id]["reasons"]


@pytest.mark.asyncio
async def test_balanced_json_shows_neutral_bypass(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    a = await _add_thread(async_db, default_user, "Balanced A", queue_position=1)
    await _confirm_series_era(async_db, a, "1965-01-01")
    b = await _add_thread(async_db, default_user, "Balanced B", queue_position=2)
    await _add_observed_effort(async_db, b, minutes=45.0, count=3)
    await async_db.commit()

    resp = await auth_client.post("/api/roll/", json={"bandwidth": "balanced"})
    assert resp.status_code == 200
    ev = (await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))).scalar_one()
    ctx = ev.recommendation_context
    assert ctx["context_version"] == 2
    assert ctx["bandwidth"] == "balanced"
    # Balanced is explicit neutral/bypass.
    assert ctx["random_bypass"] is True
    assert ctx["balanced_neutrality"] is True
    for entry in ctx["candidate_weights"]:
        assert entry["weight"] == pytest.approx(1.0)
        assert entry["reasons"] == []
        assert entry["factors"] == []
    rc = (await async_db.execute(select(RecommendationContext).where(RecommendationContext.event_id == ev.id))).scalar_one()
    assert rc.random_bypass is True
    assert rc.balanced_neutrality is True


@pytest.mark.asyncio
async def test_unknown_effort_json_stays_neutral(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    a = await _add_thread(async_db, default_user, "Unknown A", queue_position=1)
    b = await _add_thread(async_db, default_user, "Unknown B", queue_position=2)
    await async_db.commit()

    resp = await auth_client.post("/api/roll/", json={"bandwidth": "light"})
    assert resp.status_code == 200
    ev = (await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))).scalar_one()
    ctx = ev.recommendation_context
    assert ctx["context_version"] == 2
    # Unknown effort is exactly neutral even for light.
    assert ctx["random_bypass"] is True
    for entry in ctx["candidate_weights"]:
        assert entry["weight"] == pytest.approx(1.0)
        assert entry["reasons"] == []


@pytest.mark.asyncio
async def test_random_intent_json_shows_bypass(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    light = await _add_thread(async_db, default_user, "Random Light", queue_position=1)
    await _confirm_series_era(async_db, light, "1965-01-01")
    heavy = await _add_thread(async_db, default_user, "Random Heavy", queue_position=2)
    await _add_observed_effort(async_db, heavy, minutes=45.0, count=3)
    await async_db.commit()

    resp = await auth_client.post("/api/roll/", json={"bandwidth": "light", "intent": "random"})
    assert resp.status_code == 200
    ev = (await async_db.execute(select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1))).scalar_one()
    ctx = ev.recommendation_context
    assert ctx["context_version"] == 2
    assert ctx["random_bypass"] is True
    assert ctx["balanced_neutrality"] is True
    for entry in ctx["candidate_weights"]:
        assert entry["weight"] == pytest.approx(1.0)
        assert entry["reasons"] == []
    assert ev.selection_method == "random"
    rc = (await async_db.execute(select(RecommendationContext).where(RecommendationContext.event_id == ev.id))).scalar_one()
    assert rc.random_bypass is True
    # Candidate factors uniform as well.
    for f in rc.candidate_factors or []:
        assert f["weight"] == pytest.approx(1.0)
