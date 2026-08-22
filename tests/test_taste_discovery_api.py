"""Tests for Taste Bank discovery eligibility, prompts, and verdicts (issue #1750)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.taste_signal import TasteSignal, apply_inferred_evidence
from app.services.taste_bank import (
    DISMISSAL_SUPPRESSION_DAYS,
    PROMPT_COOLDOWN_DAYS,
    build_discovery_prompt,
    is_prompt_eligible,
    rank_prompt_eligible,
)

NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)


def make_signal(**overrides) -> TasteSignal:
    """Build a strong default creator-writer signal for rule tests.

    Args:
        **overrides: Column values to replace on the defaults.

    Returns:
        An unsaved TasteSignal.
    """
    defaults: dict = {
        "user_id": 1,
        "feature_type": "creator",
        "feature_key": "alan_moore",
        "creator_role": "writer",
        "label": "Alan Moore",
        "evidence_count": 5,
        "distinct_threads": 3,
        "affinity_delta": 1.2,
    }
    defaults.update(overrides)
    return TasteSignal(**defaults)


def days_ago(days: float) -> datetime:
    """Return a UTC timestamp ``days`` before NOW.

    Args:
        days: Number of days before NOW.

    Returns:
        Timezone-aware datetime.
    """
    return NOW - timedelta(days=days)


class TestPromptEligibilityRules:
    """Centralized deterministic eligibility rules."""

    def test_strong_diverse_pattern_is_eligible(self) -> None:
        assert is_prompt_eligible(make_signal(), now=NOW) is True

    def test_sparse_evidence_is_never_promoted(self) -> None:
        signal = make_signal(evidence_count=2)
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_weak_effect_does_not_become_a_prompt(self) -> None:
        signal = make_signal(affinity_delta=0.2)
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_single_thread_evidence_fails_diversity(self) -> None:
        signal = make_signal(distinct_threads=1)
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_recently_prompted_signal_is_suppressed(self) -> None:
        signal = make_signal(prompted_at=days_ago(PROMPT_COOLDOWN_DAYS - 1))
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_prompt_cooldown_expiry_allows_reprompt(self) -> None:
        signal = make_signal(prompted_at=days_ago(PROMPT_COOLDOWN_DAYS + 1))
        assert is_prompt_eligible(signal, now=NOW) is True

    def test_rejected_signal_never_prompts_again(self) -> None:
        signal = make_signal(verdict="rejected", prompted_at=days_ago(365))
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_confirmed_and_sometimes_signals_stop_prompting(self) -> None:
        for verdict in ("confirmed", "sometimes"):
            signal = make_signal(verdict=verdict)
            assert is_prompt_eligible(signal, now=NOW) is False

    def test_recent_dismissal_suppresses_prompting(self) -> None:
        signal = make_signal(dismissed_at=days_ago(DISMISSAL_SUPPRESSION_DAYS - 1))
        assert is_prompt_eligible(signal, now=NOW) is False

    def test_old_dismissal_suppression_expires(self) -> None:
        signal = make_signal(dismissed_at=days_ago(DISMISSAL_SUPPRESSION_DAYS + 1))
        assert is_prompt_eligible(signal, now=NOW) is True

    def test_rank_orders_by_strength_and_filters_ineligible(self) -> None:
        weak = make_signal(feature_key="weak", evidence_count=1)
        mid = make_signal(
            feature_key="mid", affinity_delta=0.8, evidence_count=4
        )
        top = make_signal(feature_key="top", affinity_delta=1.5, evidence_count=6)
        ineligible = make_signal(feature_key="nope", verdict="rejected")

        ranked = rank_prompt_eligible([mid, weak, ineligible, top], now=NOW)

        assert [signal.feature_key for signal in ranked] == ["top", "mid"]

    def test_creator_role_specific_writer_copy(self) -> None:
        prompt = build_discovery_prompt(make_signal())
        assert prompt == (
            "You've rated comics written by Alan Moore well above your usual "
            "baseline across 5 reads. Is Alan Moore generally a draw for you?"
        )

    def test_artist_role_copy_mentions_art(self) -> None:
        prompt = build_discovery_prompt(
            make_signal(
                feature_key="jim_lee", creator_role="artist", label="Jim Lee"
            )
        )
        assert "art by Jim Lee" in prompt

    def test_non_creator_series_copy(self) -> None:
        prompt = build_discovery_prompt(
            make_signal(
                feature_type="series",
                creator_role=None,
                feature_key="watchmen",
                label="Watchmen",
            )
        )
        assert prompt.startswith("You've rated Watchmen issues")
        assert "Do you generally enjoy Watchmen?" in prompt


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
    """End-to-end discovery listing and response flows."""

    async def seed_signal(self, db: AsyncSession, **overrides) -> TasteSignal:
        """Persist one taste signal for the primary test user.

        Args:
            db: Async database session.
            **overrides: Column overrides applied to strong defaults.

        Returns:
            The persisted signal (flushed, id assigned).
        """
        defaults: dict = {
            "user_id": 1,
            "feature_type": "creator",
            "feature_key": "alan_moore",
            "creator_role": "writer",
            "label": "Alan Moore",
            "evidence_count": 5,
            "distinct_threads": 3,
            "affinity_delta": 1.2,
        }
        defaults.update(overrides)
        signal = TasteSignal(**defaults)
        db.add(signal)
        await db.flush()
        return signal

    async def test_only_eligible_discoveries_are_returned(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Weak, already-verdict, and suppressed signals stay hidden."""
        await self.seed_signal(async_db)  # eligible
        await self.seed_signal(
            async_db, feature_key="sparse", label="Sparse", evidence_count=1
        )  # too little evidence
        await self.seed_signal(
            async_db, feature_key="done", label="Done", verdict="confirmed"
        )  # explicit verdict

        response = await auth_client.get("/api/v1/taste/discoveries")

        assert response.status_code == 200
        data = response.json()
        assert len(data["discoveries"]) == 1
        discovery = data["discoveries"][0]
        assert discovery["feature_type"] == "creator"
        assert discovery["creator_role"] == "writer"
        assert discovery["label"] == "Alan Moore"
        assert "Alan Moore" in discovery["prompt"]
        assert discovery["evidence_count"] == 5
        assert discovery["distinct_threads"] == 3

    async def test_listing_records_prompt_for_cooldown(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Surfacing starts the prompt cooldown so repeats are suppressed."""
        signal = await self.seed_signal(async_db)

        first = await auth_client.get("/api/v1/taste/discoveries")
        assert len(first.json()["discoveries"]) == 1

        refreshed = await async_db.execute(
            select(TasteSignal).where(TasteSignal.id == signal.id)
        )
        stored = refreshed.scalar_one()
        assert stored.prompt_count == 1
        assert stored.prompted_at is not None

        second = await auth_client.get("/api/v1/taste/discoveries")
        assert second.status_code == 200
        assert second.json()["discoveries"] == []

    async def test_verdict_updates_signal_and_stops_prompting(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Confirm/sometimes/reject each end prompting for that signal."""
        for verdict in ("confirmed", "sometimes", "rejected"):
            signal = await self.seed_signal(
                async_db, feature_key=f"key-{verdict}", label=f"Label {verdict}"
            )

            response = await auth_client.post(
                f"/api/v1/taste/discoveries/{signal.id}/verdict",
                json={"verdict": verdict},
            )

            assert response.status_code == 200
            body = response.json()
            assert body["id"] == signal.id
            assert body["verdict"] == verdict
            assert body["verdict_at"] is not None

            listed = await auth_client.get("/api/v1/taste/discoveries")
            labels = [
                item["label"] for item in listed.json()["discoveries"]
            ]
            assert f"Label {verdict}" not in labels

    async def test_repeated_verdict_submission_is_idempotent(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Re-submitting a verdict updates the same row without duplicates."""
        signal = await self.seed_signal(async_db)

        for _ in range(2):
            response = await auth_client.post(
                f"/api/v1/taste/discoveries/{signal.id}/verdict",
                json={"verdict": "sometimes"},
            )
            assert response.status_code == 200

        count_result = await async_db.execute(select(TasteSignal))
        assert len(count_result.scalars().all()) == 1

        refreshed = await async_db.execute(
            select(TasteSignal).where(TasteSignal.id == signal.id)
        )
        stored = refreshed.scalar_one()
        assert stored.verdict == "sometimes"

    async def test_invalid_verdict_payload_rejected(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Unknown verdict strings fail validation."""
        signal = await self.seed_signal(async_db)

        response = await auth_client.post(
            f"/api/v1/taste/discoveries/{signal.id}/verdict",
            json={"verdict": "sure-why-not"},
        )

        assert response.status_code == 422
        refreshed = await async_db.execute(
            select(TasteSignal).where(TasteSignal.id == signal.id)
        )
        assert refreshed.scalar_one().verdict is None

    async def test_dismissal_suppresses_without_confirmation(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """Dismissing hides the card temporarily but never sets a verdict."""
        signal = await self.seed_signal(async_db)

        response = await auth_client.post(
            f"/api/v1/taste/discoveries/{signal.id}/dismiss"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["verdict"] is None
        assert body["dismissed_at"] is not None

        suppressed = await auth_client.get("/api/v1/taste/discoveries")
        assert suppressed.json()["discoveries"] == []

        # Once the dismissal window passes, the inferred pattern may ask again.
        stored = await async_db.get(TasteSignal, signal.id)
        stored.dismissed_at = datetime.now(UTC) - timedelta(
            days=DISMISSAL_SUPPRESSION_DAYS + 1
        )
        await async_db.commit()

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

        verdict_response = await auth_client.post(
            f"/api/v1/taste/discoveries/{foreign.id}/verdict",
            json={"verdict": "confirmed"},
        )
        assert verdict_response.status_code == 404

        dismiss_response = await auth_client.post(
            f"/api/v1/taste/discoveries/{foreign.id}/dismiss"
        )
        assert dismiss_response.status_code == 404

        refreshed = await async_db.get(TasteSignal, foreign.id)
        assert refreshed.verdict is None
        assert refreshed.dismissed_at is None

    async def test_missing_signal_returns_404(
        self, auth_client: AsyncClient
    ) -> None:
        """Unknown discovery ids respond with 404, not a crash."""
        missing = await auth_client.post(
            "/api/v1/taste/discoveries/999999/verdict",
            json={"verdict": "confirmed"},
        )
        assert missing.status_code == 404

        dismissed = await auth_client.post("/api/v1/taste/discoveries/999999/dismiss")
        assert dismissed.status_code == 404

    async def test_unauthenticated_requests_are_rejected(
        self, client: AsyncClient
    ) -> None:
        """The discovery surface requires authentication."""
        listed = await client.get("/api/v1/taste/discoveries")
        assert listed.status_code == 401

        responded = await client.post(
            "/api/v1/taste/discoveries/1/verdict", json={"verdict": "confirmed"}
        )
        assert responded.status_code == 401

    async def test_limit_bounds_results(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """The limit parameter caps how many discoveries are returned."""
        for index in range(3):
            await self.seed_signal(
                async_db,
                feature_key=f"batch-{index}",
                label=f"Batch {index}",
                affinity_delta=1.0 + index / 10,
            )

        response = await auth_client.get("/api/v1/taste/discoveries?limit=1")

        assert response.status_code == 200
        assert len(response.json()["discoveries"]) == 1


@pytest.mark.asyncio
async def test_explicit_verdict_survives_inference_refresh(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A later inference refresh must not overwrite an explicit verdict."""
    signal = await apply_inferred_evidence_to_new_signal(async_db)
    assert signal.verdict is None

    verdict_response = await auth_client.post(
        f"/api/v1/taste/discoveries/{signal.id}/verdict",
        json={"verdict": "confirmed"},
    )
    assert verdict_response.status_code == 200

    apply_inferred_evidence(
        signal,
        evidence_count=99,
        distinct_threads=50,
        affinity_delta=9.9,
    )
    await async_db.commit()

    refreshed = await async_db.get(TasteSignal, signal.id)
    assert refreshed.verdict == "confirmed"
    assert refreshed.verdict_at is not None
    assert refreshed.evidence_count == 99


async def apply_inferred_evidence_to_new_signal(db: AsyncSession) -> TasteSignal:
    """Create a fresh inferred signal through the canonical inference path.

    Args:
        db: Async database session.

    Returns:
        The persisted signal.
    """
    signal = TasteSignal(
        user_id=1,
        feature_type="creator",
        feature_key="grant_morrison",
        creator_role="writer",
        label="Grant Morrison",
        evidence_count=3,
        distinct_threads=2,
        affinity_delta=0.7,
    )
    db.add(signal)
    await db.flush()
    return signal
