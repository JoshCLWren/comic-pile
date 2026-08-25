"""Tests for documented bandwidth weighting inside the bounded roll pool.

Covers the #1715 integration: the pure #1712 weight table applied to the
die-bounded pool, the Phase 1 effort pipeline feeding it, and the roll
endpoint's additive response semantics.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Session as SessionModel, Thread
from app.services.bandwidth_roll_weighting import (
    build_bandwidth_candidate_weights,
    build_user_effort_summary,
    load_user_decision_events,
    resolve_bandwidth_weights,
    resolve_candidate_efforts,
)
from tests.conftest import get_or_create_user_async


def _rows(*thread_ids: int) -> list[tuple[object, int, object]]:
    """Build pool rows carrying distinct thread ids in pool order."""
    return [(SimpleNamespace(id=thread_id), 3, None) for thread_id in thread_ids]


class TestDocumentedWeightTable:
    """Weights must come from the centralized #1712 cap table, not ad-hoc math."""

    def test_light_uses_documented_band_weights(self) -> None:
        rows = _rows(1, 2, 3)
        efforts = [(1, 6.0), (2, 15.0), (3, 30.0)]
        weights, applied = build_bandwidth_candidate_weights(rows, efforts, "light")
        assert weights == [1.5, 1.0, 0.75]
        assert applied is True

    def test_deep_uses_documented_band_weights(self) -> None:
        rows = _rows(1, 2, 3)
        efforts = [(1, 6.0), (2, 15.0), (3, 30.0)]
        weights, applied = build_bandwidth_candidate_weights(rows, efforts, "deep")
        assert weights == [0.9, 1.0, 1.25]
        assert applied is True

    def test_balanced_is_exactly_neutral(self) -> None:
        rows = _rows(1, 2)
        efforts = [(1, 6.0), (2, 30.0)]
        weights, applied = build_bandwidth_candidate_weights(rows, efforts, "balanced")
        assert weights == [1.0, 1.0]
        assert applied is False

    def test_unknown_mode_normalizes_to_balanced(self) -> None:
        rows = _rows(1, 2)
        efforts = [(1, 6.0), (2, 30.0)]
        weights, applied = build_bandwidth_candidate_weights(rows, efforts, "speed")
        assert weights == [1.0, 1.0]
        assert applied is False

    def test_none_bandwidth_normalizes_to_balanced(self) -> None:
        rows = _rows(1, 2)
        efforts = [(1, 6.0), (2, 30.0)]
        weights, applied = build_bandwidth_candidate_weights(rows, efforts, None)
        assert weights == [1.0, 1.0]
        assert applied is False

    def test_unknown_effort_is_neutral_in_every_mode(self) -> None:
        rows = _rows(1, 2)
        efforts = [(1, None), (2, 30.0)]
        for mode in ("light", "balanced", "deep", "nonsense"):
            weights, _ = build_bandwidth_candidate_weights(rows, efforts, mode)
            assert weights[0] == 1.0

    def test_all_positive_so_no_candidate_is_excluded(self) -> None:
        rows = _rows(1, 2, 3)
        efforts = [(1, 6.0), (2, 15.0), (3, 30.0)]
        for mode in ("light", "deep"):
            weights, _ = build_bandwidth_candidate_weights(rows, efforts, mode)
            assert all(weight > 0 for weight in weights)

    def test_light_favors_lower_effort_monotonically(self) -> None:
        rows = _rows(1, 2, 3)
        efforts = [(1, 6.0), (2, 15.0), (3, 30.0)]
        weights, _ = build_bandwidth_candidate_weights(rows, efforts, "light")
        assert weights[0] > weights[1] > weights[2]

    def test_weight_spread_stays_within_documented_caps(self) -> None:
        rows = _rows(1, 2)
        efforts = [(1, 1.0), (2, 600.0)]
        light_weights, _ = build_bandwidth_candidate_weights(rows, efforts, "light")
        deep_weights, _ = build_bandwidth_candidate_weights(rows, efforts, "deep")
        assert max(light_weights) / min(light_weights) <= 1.5 / 0.75 + 1e-9
        assert max(deep_weights) / min(deep_weights) <= 1.25 / 0.9 + 1e-9

    def test_equal_efforts_stay_equal_and_unapplied(self) -> None:
        rows = _rows(1, 2, 3)
        efforts = [(1, 10.0), (2, 20.0), (3, 30.0)]
        unknown = [(1, None), (2, None), (3, None)]
        for candidate_efforts in (efforts, unknown):
            weights, applied = build_bandwidth_candidate_weights(
                rows, candidate_efforts, "light"
            )
            assert len(set(weights)) == 1
            assert applied is False

    def test_single_candidate_pool_reports_unapplied(self) -> None:
        rows = _rows(7)
        weights, applied = build_bandwidth_candidate_weights(rows, [(7, 6.0)], "light")
        assert weights == [1.5]
        assert applied is False

    def test_empty_pool_yields_no_weights(self) -> None:
        weights, applied = build_bandwidth_candidate_weights([], [], "light")
        assert weights == []
        assert applied is False

    def test_output_order_matches_pool_order(self) -> None:
        rows = _rows(9, 4, 6)
        efforts = [(9, 30.0), (4, 6.0), (6, 15.0)]
        weights, _ = build_bandwidth_candidate_weights(rows, efforts, "light")
        assert weights == [0.75, 1.5, 1.0]


def _latency_events(
    session_id: int,
    thread_id: int,
    *,
    count: int,
    duration_seconds: float,
    start: datetime,
) -> list[Event]:
    """Build linked roll/rate event pairs with fixed elapsed durations."""
    events: list[Event] = []
    rolls: list[Event] = []
    for offset in range(count):
        rolled_at = start + timedelta(minutes=offset * 10)
        rolls.append(
            Event(
                type="roll",
                session_id=session_id,
                selected_thread_id=thread_id,
                timestamp=rolled_at,
            )
        )
    events.extend(rolls)
    for offset, roll_event in enumerate(rolls):
        events.append(
            Event(
                type="rate",
                session_id=session_id,
                thread_id=thread_id,
                rating=4.0,
                issues_read=1,
                source_roll_event_id=-(offset + 1),
                timestamp=roll_event.timestamp + timedelta(seconds=duration_seconds),
            )
        )
    return events


async def _seed_history(
    async_db: AsyncSession,
    user_id: int,
    entries: list[tuple[int, float]],
) -> dict[int, Thread]:
    """Persist linked roll/rate histories; entries are (thread_id, seconds)."""
    reading_session = SessionModel(user_id=user_id)
    async_db.add(reading_session)
    await async_db.flush()

    threads: dict[int, Thread] = {}
    pending_links: list[tuple[Event, Event]] = []
    base = datetime.now(UTC) - timedelta(days=2)
    for index, (thread_key, duration_seconds) in enumerate(entries):
        if thread_key not in threads:
            thread = Thread(
                title=f"Thread {thread_key}",
                format="Comic",
                issues_remaining=5,
                queue_position=len(threads) + 1,
                status="active",
                user_id=user_id,
            )
            async_db.add(thread)
            await async_db.flush()
            threads[thread_key] = thread

        pair = _latency_events(
            reading_session.id,
            threads[thread_key].id,
            count=1,
            duration_seconds=duration_seconds,
            start=base + timedelta(hours=index),
        )
        roll_event, rate_event = pair
        async_db.add_all(pair)
        await async_db.flush()
        pending_links.append((roll_event, rate_event))

    for roll_event, rate_event in pending_links:
        rate_event.source_roll_event_id = roll_event.id
    await async_db.flush()
    return threads


@pytest.mark.asyncio
class TestEffortPipelineIntegration:
    """The Phase 0/1 pipeline feeds trusted per-thread minutes to the weights."""

    async def test_trusted_history_resolves_minutes(self, async_db: AsyncSession) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(11, 300.0), (12, 3600.0)])

        events = await load_user_decision_events(async_db, user.id)
        summary = build_user_effort_summary(events)
        efforts = resolve_candidate_efforts(summary, _rows(12, 11))

        assert efforts == [(12, 60.0), (11, 5.0)]

    async def test_invalid_durations_are_excluded(self, async_db: AsyncSession) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(21, 5.0), (22, 60000.0)])

        events = await load_user_decision_events(async_db, user.id)
        summary = build_user_effort_summary(events)

        assert summary.threads == {}

    async def test_sparse_history_stays_neutral(self, async_db: AsyncSession) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(31, 300.0), (32, 420.0)])

        events = await load_user_decision_events(async_db, user.id)
        summary = build_user_effort_summary(events)
        efforts = resolve_candidate_efforts(summary, _rows(31))

        assert efforts == [(31, None)]

    async def test_history_is_scoped_to_one_reader(self, async_db: AsyncSession) -> None:
        reader = await get_or_create_user_async(async_db)
        other = await get_or_create_user_async(async_db, username="other-bandwidth-reader")
        await _seed_history(async_db, reader.id, [(41, 300.0)])
        await _seed_history(async_db, other.id, [(42, 3600.0)])

        own_events = await load_user_decision_events(async_db, reader.id)
        summary = build_user_effort_summary(own_events)

        assert set(summary.threads) == {41}

    async def test_resolve_bandwidth_weights_end_to_end(
        self, async_db: AsyncSession
    ) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(51, 300.0), (52, 3600.0)])

        rows = _rows(51, 52)
        weights, applied = await resolve_bandwidth_weights(
            async_db, user_id=user.id, bounded_rows=rows, bandwidth="deep"
        )

        assert weights == [0.9, 1.25]
        assert applied is True

    async def test_resolve_bandwidth_weights_without_history_is_neutral(
        self, async_db: AsyncSession
    ) -> None:
        user = await get_or_create_user_async(async_db)
        rows = _rows(61, 62)

        weights, applied = await resolve_bandwidth_weights(
            async_db, user_id=user.id, bounded_rows=rows, bandwidth="light"
        )

        assert weights == [1.0, 1.0]
        assert applied is False

    async def test_load_user_decision_events_filters_types(
        self, async_db: AsyncSession
    ) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(71, 300.0)])
        noise = Event(type="snooze", thread_id=None)
        async_db.add(noise)
        await async_db.flush()

        events = await load_user_decision_events(async_db, user.id)

        assert {event.type for event in events} <= {"roll", "rate"}


@pytest.mark.asyncio
class TestRollEndpointBandwidthSemantics:
    """Roll responses stay backward compatible and report bandwidth honestly."""

    async def test_explicit_light_bandwidth_reports_weighting(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(81, 300.0), (82, 3600.0)])

        response = await auth_client.post("/api/v1/roll/", json={"bandwidth": "light"})

        assert response.status_code == 200
        data = response.json()
        assert "bandwidth_weighted" in data["recommendation_reason_codes"]
        assert data["selection_method"] in {"bandwidth", "momentum_weighted"}

    async def test_default_roll_preserves_legacy_semantics(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        user = await get_or_create_user_async(async_db)
        await _seed_history(async_db, user.id, [(91, 300.0), (92, 3600.0)])

        response = await auth_client.post("/api/v1/roll/")

        assert response.status_code == 200
        data = response.json()
        assert "bandwidth_weighted" not in data["recommendation_reason_codes"]
        assert data["recommendation_reason_codes"] in (
            ["pure_random"],
            ["momentum_weighted"],
        )
