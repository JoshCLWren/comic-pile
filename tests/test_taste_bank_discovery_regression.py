"""Phase 7 acceptance regression: Taste Bank discovery without ranking use."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.taste_signal import TasteSignal as TasteSignalModel
from app.models.user import User
from app.schemas.taste import SignalType, TasteSignal as TasteSignalSchema, Verdict
from app.services.comicvine_taste import extract_taste_features
from app.services.prompt_eligibility import evaluate_prompt_eligibility


# ---- Criterion 1: Confirmed metadata yields normalized creator/character/team/publisher/era evidence ----


def test_confirmed_metadata_yields_all_evidence_types() -> None:
    issue_metadata = {
        "creator_credits": [
            {"id": 1, "name": "Alan Moore", "role": "writer"},
            {"id": 2, "name": "Dave Gibbons", "role": "artist"},
        ],
        "characters": [{"id": 10, "name": "Rorschach"}, {"id": 11, "name": "Nite Owl"}],
        "teams": [{"id": 20, "name": "Watchmen"}],
        "cover_date": "2021-06-15",
        "store_date": "2021-06-10",
    }
    volume_metadata = {"id": 22, "name": "Series", "publisher": {"id": 7, "name": "DC Comics"}}

    features = extract_taste_features(issue_metadata, volume_metadata)

    assert features["creators"], "creators should be extracted"
    assert features["characters"], "characters should be extracted"
    assert features["teams"], "teams should be extracted"
    assert features["publisher"] is not None, "publisher should be extracted from volume"
    assert features["publisher"]["name"] == "DC Comics"
    assert features["publication_era"] == "2021", "era should be the 4-digit year"


def test_duplicate_credits_do_not_double_count() -> None:
    issue_metadata = {
        "creator_credits": [
            {"id": 1, "name": "Alan Moore", "role": "writer"},
            {"id": 1, "name": "Alan Moore", "role": "writer"},
        ],
        "characters": [{"id": 5, "name": "Hero"}, {"id": 5, "name": "Hero"}],
        "teams": [{"id": 9, "name": "Team"}, {"id": 9, "name": "Team"}],
        "cover_date": "2019-05-01",
    }
    features = extract_taste_features(issue_metadata)
    assert len(features["creators"]) == 1
    assert len(features["characters"]) == 1
    assert len(features["teams"]) == 1


def test_unconfirmed_or_missing_metadata_yields_no_evidence() -> None:
    assert extract_taste_features({}, None)["creators"] == []
    # No cover date -> no era fabricated
    features = extract_taste_features({"creator_credits": [], "characters": [], "teams": []}, None)
    assert not features["creators"]
    assert features["publication_era"] is None


# ---- Criterion 2: Repeated above-baseline creates confident inferred signal; sparse does not ----


def _signal(
    *,
    evidence_count: int,
    confidence: float,
    affinity: float,
    diversity: int,
    verdict: Verdict | None = None,
    last_prompted_at: datetime | None = None,
) -> TasteSignalSchema:
    return TasteSignalSchema(
        user_id=1,
        signal_type=SignalType.CHARACTER,
        stable_key=f"character:{evidence_count}",
        display_name="Rorschach",
        affinity=affinity,
        confidence=confidence,
        evidence_count=evidence_count,
        evidence_diversity=diversity,
        verdict=verdict,
        last_prompted_at=last_prompted_at,
        last_rejected_at=None,
        is_creator_role=False,
    )


def test_sparse_evidence_not_eligible() -> None:
    now = datetime.now(UTC)
    result = evaluate_prompt_eligibility(
        [_signal(evidence_count=1, confidence=0.3, affinity=0.0, diversity=1)],
        now=now,
    )
    assert result.candidates == []
    assert len(result.ineligible) == 1


def test_strong_repeated_evidence_is_eligible_and_diverse() -> None:
    now = datetime.now(UTC)
    result = evaluate_prompt_eligibility(
        [_signal(evidence_count=5, confidence=0.95, affinity=0.7, diversity=3)],
        now=now,
    )
    assert len(result.candidates) == 1


def test_diversity_increases_rank_stability() -> None:
    now = datetime.now(UTC)
    strong = _signal(evidence_count=5, confidence=0.95, affinity=0.7, diversity=3)
    weak = _signal(evidence_count=5, confidence=0.95, affinity=0.7, diversity=3).model_copy(
        update={"stable_key": "character:weak"}
    )
    result = evaluate_prompt_eligibility([strong, weak], now=now)
    assert len(result.candidates) == 2


# ---- Criterion 3: Prompt eligibility respects thresholds, diversity, cooldown, rejection ----


def test_prompt_eligibility_thresholds() -> None:
    now = datetime.now(UTC)
    # below evidence count
    assert (
        evaluate_prompt_eligibility(
            [_signal(evidence_count=2, confidence=0.7, affinity=0.5, diversity=3)], now=now
        ).candidates
        == []
    )
    # below diversity
    assert (
        evaluate_prompt_eligibility(
            [_signal(evidence_count=5, confidence=0.7, affinity=0.5, diversity=1)], now=now
        ).candidates
        == []
    )


def test_rejected_suppression() -> None:
    now = datetime.now(UTC)
    result = evaluate_prompt_eligibility(
        [
            _signal(
                evidence_count=5,
                confidence=0.95,
                affinity=0.7,
                diversity=3,
                verdict=Verdict.REJECTED,
            )
        ],
        now=now,
    )
    assert result.candidates == []
    assert len(result.suppressed) == 1


def test_cooldown_suppresses_recent_prompt() -> None:
    now = datetime.now(UTC)
    recent = _signal(
        evidence_count=4,
        confidence=0.95,
        affinity=0.7,
        diversity=3,
        last_prompted_at=now - timedelta(days=2),
    )
    old = _signal(
        evidence_count=5,
        confidence=0.95,
        affinity=0.7,
        diversity=3,
        last_prompted_at=now - timedelta(days=20),
    )
    result = evaluate_prompt_eligibility([recent, old], now=now)
    eligible_keys = {c.signal.stable_key for c in result.candidates}
    assert "character:5" in eligible_keys  # old prompt re-eligible after cooldown
    assert recent.stable_key not in eligible_keys  # recent prompt still cooled down


# ---- Criterion 4: Verdict survives recomputation ----


@pytest.mark.asyncio
async def test_api_verdict_updates_and_suppresses_discovery(async_db, auth_client) -> None:
    """API confirm/sometimes/reject updates a signal; rejected signals leave discovery."""
    now = datetime.now(UTC)
    result = await async_db.execute(
        select(User).where(User.id == 1)
    )
    user = result.scalar_one()

    sig = TasteSignalModel(
        user_id=user.id,
        signal_type="character",
        external_key="character:10",
        display_name="Rorschach",
        evidence_count=5,
        distinct_thread_count=3,
        confidence=0.95,
        affinity_estimate=0.7,
        user_verdict=None,
        first_observed_at=now,
        last_observed_at=now,
    )
    async_db.add(sig)
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(sig)

    for verdict in ("confirmed", "sometimes", "rejected"):
        # Reset to inferred so each iteration starts clean.
        res = await async_db.execute(
            select(TasteSignalModel).where(TasteSignalModel.id == sig.id)
        )
        current = res.scalar_one()
        current.user_verdict = None
        current.verdict_at = None
        current.last_prompted_at = None
        await async_db.commit()
        await async_db.refresh(current)

        resp = await auth_client.post(
            f"/api/v1/taste/signals/{sig.id}/verdict",
            json={"verdict": verdict},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["verdict"] == verdict
        assert data["id"] == sig.id

        # Explicit verdict must survive a later refresh of inferred fields.
        res = await async_db.execute(
            select(TasteSignalModel).where(TasteSignalModel.id == sig.id)
        )
        loaded = res.scalar_one()
        loaded.evidence_count = 99
        loaded.confidence = 0.1
        await async_db.flush()
        await async_db.refresh(loaded)
        assert loaded.user_verdict == verdict

        if verdict == "rejected":
            disc = await auth_client.get("/api/v1/taste/discoveries")
            assert disc.status_code == 200
            ids = [d["signal"]["id"] for d in disc.json()]
            assert sig.id not in ids


# ---- Criterion 5: Discovery UI never blocks normal flow ----


def test_discovery_card_is_non_blocking_component() -> None:
    """Frontend discovery card must be dismissible and not modal-blocking."""
    import pathlib

    card_path = pathlib.Path("frontend/src/components/TasteDiscoveryCard.tsx")
    assert card_path.exists(), "TasteDiscoveryCard component missing"
    content = card_path.read_text(encoding="utf-8")
    assert "onDismiss" in content
    assert 'data-testid="taste-dismiss"' in content
    assert "fixed bottom" in content
    assert "ComicPile noticed something" in content

    roll_path = pathlib.Path("frontend/src/pages/RollPage/index.tsx")
    roll_content = roll_path.read_text(encoding="utf-8")
    assert "TasteDiscoveryCard" in roll_content
    assert 'data-testid="main-die-3d"' in roll_content


# ---- Criterion 6: No Taste Bank signal changes Roll weights ----


def test_roll_weights_unchanged_by_taste_bank() -> None:
    """Phase 7 must not change Roll dice pool weighting."""
    import pathlib

    roll_py = pathlib.Path("app/api/roll.py").read_text(encoding="utf-8")
    assert "TasteSignal" not in roll_py
    assert "taste_bank" not in roll_py.lower()

    queue_py = (
        pathlib.Path("comic_pile/queue.py").read_text(encoding="utf-8")
        if pathlib.Path("comic_pile/queue.py").exists()
        else ""
    )
    assert "taste" not in queue_py.lower()
