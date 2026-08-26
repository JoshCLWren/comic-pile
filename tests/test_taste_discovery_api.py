"""Tests for the Taste Bank discovery card API and rules (issue #1750).

Covers the durable-signal discovery surface: only eligible inferred signals
surface, prompting starts the canonical cooldown, dismissal suppresses
without ever recording a verdict, and every route is ownership-scoped.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.taste_signal import SIGNAL_CREATOR, SIGNAL_CHARACTER, TasteSignal
from app.services.prompt_eligibility import DEFAULT_CONFIG
from app.services.taste_bank import build_discovery_prompt


def make_signal(**overrides: object) -> TasteSignal:
    """Build a strong default creator-writer signal for rule tests.

    The defaults clear every eligibility threshold from the canonical engine
    (evidence >= 3, confidence >= 0.6, |affinity| >= 0.3, diversity >= 2).

    Args:
        **overrides: Column values to replace on the defaults.

    Returns:
        An unsaved TasteSignal.
    """
    signal = TasteSignal(
        user_id=1,
        signal_type=SIGNAL_CREATOR,
        external_key="creator:writer:alan-moore",
        display_name="Alan Moore",
        affinity_estimate=0.9,
        confidence=0.82,
        evidence_count=5,
        distinct_thread_count=3,
    )
    for name, value in overrides.items():
        setattr(signal, name, value)
    return signal


def days_before_now(days: float) -> datetime:
    """Return a UTC timestamp ``days`` before the real current time.

    Args:
        days: Number of days before now.

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.now(UTC) - timedelta(days=days)


class TestDiscoveryPromptCopy:
    """Human-readable copy for one eligible signal."""

    def test_creator_writer_copy_names_the_role_and_evidence(self) -> None:
        """Writer-role keys produce role-specific copy with evidence context."""
        prompt = build_discovery_prompt(make_signal())

        assert prompt == (
            "You've rated comics written by Alan Moore well above your usual "
            "baseline across 5 reads. Is Alan Moore generally a draw for you?"
        )

    def test_artist_role_copy_mentions_art(self) -> None:
        """Artist-role keys describe the art rather than the writing."""
        prompt = build_discovery_prompt(
            make_signal(
                external_key="creator:artist:jim-lee",
                display_name="Jim Lee",
            )
        )

        assert "art by Jim Lee" in prompt

    def test_non_creator_copy_uses_the_display_name(self) -> None:
        """Non-creator signals ask about the feature itself."""
        prompt = build_discovery_prompt(
            make_signal(
                signal_type=SIGNAL_CHARACTER,
                external_key="character:batman",
                display_name="Batman",
                evidence_count=6,
            )
        )

        assert prompt == (
            "You've rated Batman issues well above your usual baseline "
            "across 6 reads. Do you generally enjoy Batman?"
        )


@pytest.mark.asyncio
async def _seed_user(db: AsyncSession, username: str = "taste_other") -> User:
    """Create and persist a secondary user for ownership tests.

    Args:
        db: Async database session.
        username: Username for the new user.

    Returns:
        The persisted user.
    """
    user = User(username=username, created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
class TestDiscoveryAPI:
    """End-to-end discovery listing, cooldown, and dismissal flows."""

    async def seed_signal(self, db: AsyncSession, **overrides: object) -> TasteSignal:
        """Persist one strong taste signal for the primary test user.

        Args:
            db: Async database session.
            **overrides: Column overrides applied to strong defaults.

        Returns:
            The persisted signal (flushed, id assigned).
        """
        signal = make_signal(**overrides)
        db.add(signal)
        await db.flush()
        return signal

    async def test_only_eligible_discoveries_are_returned(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Sparse evidence and explicit verdicts stay hidden; strength surfaces."""
        await self.seed_signal(async_db)
        await self.seed_signal(
            async_db,
            external_key="creator:writer:sparse",
            display_name="Sparse",
            evidence_count=2,
        )
        await self.seed_signal(
            async_db,
            external_key="creator:writer:done",
            display_name="Done",
            user_verdict="confirmed",
        )

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        data = response.json()
        assert len(data["discoveries"]) == 1
        discovery = data["discoveries"][0]
        assert discovery["signal_type"] == "creator"
        assert discovery["external_key"] == "creator:writer:alan-moore"
        assert discovery["display_name"] == "Alan Moore"
        assert "Alan Moore" in discovery["prompt"]
        assert discovery["evidence_count"] == 5
        assert discovery["distinct_thread_count"] == 3

    async def test_weak_effect_and_low_confidence_stay_hidden(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Signals below the affinity or confidence gates never become prompts."""
        await self.seed_signal(
            async_db,
            external_key="creator:writer:weak",
            display_name="Weak",
            affinity_estimate=0.2,
        )
        await self.seed_signal(
            async_db,
            external_key="creator:writer:unsure",
            display_name="Unsure",
            confidence=0.4,
        )

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        assert response.json()["discoveries"] == []

    async def test_single_thread_evidence_fails_diversity(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Evidence from one thread only is not diverse enough to prompt."""
        await self.seed_signal(async_db, distinct_thread_count=1)

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        assert response.json()["discoveries"] == []

    async def test_listing_records_prompt_and_starts_cooldown(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Surfacing records ``last_prompted_at`` so repeats are suppressed."""
        signal = await self.seed_signal(async_db)

        first = await auth_client.get("/api/v1/taste/discoveries")
        assert len(first.json()["discoveries"]) == 1

        stored = await async_db.get(TasteSignal, signal.id)
        assert stored is not None
        assert stored.last_prompted_at is not None

        second = await auth_client.get("/api/v1/taste/discoveries")
        assert second.status_code == 200
        assert second.json()["discoveries"] == []

    async def test_cooldown_expiry_allows_reprompting(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """A signal prompted outside the cooldown window may ask again."""
        await self.seed_signal(
            async_db,
            last_prompted_at=days_before_now(DEFAULT_CONFIG.cooldown_days + 1),
        )

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        discoveries = response.json()["discoveries"]
        assert [item["external_key"] for item in discoveries] == [
            "creator:writer:alan-moore"
        ]

    @pytest.mark.parametrize("verdict", ["confirmed", "sometimes", "rejected"])
    async def test_explicit_verdicts_are_never_surfaced(
        self, auth_client: AsyncClient, async_db: AsyncSession, verdict: str
    ) -> None:
        """Any explicit verdict removes the signal from discovery entirely."""
        await self.seed_signal(async_db, user_verdict=verdict)

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        assert response.json()["discoveries"] == []

    async def test_rank_orders_strongest_first(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Eligible discoveries are ranked strongest to weakest."""
        await self.seed_signal(
            async_db,
            external_key="creator:writer:low",
            display_name="Low",
            affinity_estimate=0.31,
            confidence=0.61,
            evidence_count=3,
            distinct_thread_count=2,
        )
        await self.seed_signal(
            async_db,
            external_key="creator:writer:mid",
            display_name="Mid",
            affinity_estimate=0.6,
            confidence=0.8,
            evidence_count=6,
            distinct_thread_count=4,
        )
        await self.seed_signal(
            async_db,
            external_key="creator:writer:top",
            display_name="Top",
            affinity_estimate=1.0,
            confidence=0.9,
            evidence_count=9,
            distinct_thread_count=6,
        )

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        names = [item["display_name"] for item in response.json()["discoveries"]]
        assert names == ["Top", "Mid", "Low"]

    async def test_limit_bounds_results(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """The limit parameter caps how many discoveries are returned."""
        for index in range(3):
            await self.seed_signal(
                async_db,
                external_key=f"creator:writer:batch-{index}",
                display_name=f"Batch {index}",
            )

        response = await auth_client.get("/api/v1/taste/discoveries?limit=1")

        assert response.status_code == 200
        assert len(response.json()["discoveries"]) == 1

    async def test_dismissal_suppresses_without_confirmation(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Dismissing hides the card temporarily but never sets a verdict."""
        signal = await self.seed_signal(async_db)

        response = await auth_client.post(f"/api/v1/taste/discoveries/{signal.id}/dismiss")

        assert response.status_code == 200
        assert response.json() == {"dismissed": True}

        stored = await async_db.get(TasteSignal, signal.id)
        assert stored is not None
        assert stored.user_verdict is None
        assert stored.verdict_at is None
        assert stored.prompt_suppressed_until is not None

        suppressed = await auth_client.get("/api/v1/taste/discoveries")
        assert suppressed.json()["discoveries"] == []

    async def test_expired_dismissal_window_allows_reprompting(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Once the dismissal window passes, the pattern may ask again."""
        signal = await self.seed_signal(async_db)

        dismissed = await auth_client.post(
            f"/api/v1/taste/discoveries/{signal.id}/dismiss"
        )
        assert dismissed.status_code == 200

        stored = await async_db.get(TasteSignal, signal.id)
        assert stored is not None
        stored.prompt_suppressed_until = datetime.now(UTC) - timedelta(days=1)
        await async_db.flush()

        later = await auth_client.get("/api/v1/taste/discoveries")
        assert [item["id"] for item in later.json()["discoveries"]] == [signal.id]

    async def test_cross_user_signal_is_invisible(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Another user's signals can neither be listed nor mutated."""
        other = await _seed_user(async_db)
        foreign = await self.seed_signal(async_db, user_id=other.id)

        listed = await auth_client.get("/api/v1/taste/discoveries")
        assert listed.json()["discoveries"] == []

        dismiss_response = await auth_client.post(
            f"/api/v1/taste/discoveries/{foreign.id}/dismiss"
        )
        assert dismiss_response.status_code == 404

        refreshed = await async_db.get(TasteSignal, foreign.id)
        assert refreshed is not None
        assert refreshed.user_verdict is None
        assert refreshed.prompt_suppressed_until is None

    async def test_missing_signal_returns_404(self, auth_client: AsyncClient) -> None:
        """Unknown discovery ids respond with 404, not a crash."""
        response = await auth_client.post("/api/v1/taste/discoveries/999999/dismiss")

        assert response.status_code == 404

    async def test_unauthenticated_requests_are_rejected(
        self, client: AsyncClient
    ) -> None:
        """The discovery surface requires authentication."""
        listed = await client.get("/api/v1/taste/discoveries")
        assert listed.status_code == 401

        dismissed = await client.post("/api/v1/taste/discoveries/1/dismiss")
        assert dismissed.status_code == 401
