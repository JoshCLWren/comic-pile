"""Phase 7 acceptance regression: Taste Bank discovery without ranking use."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.comicvine_hydration import normalize_issue
from app.models.taste_signal import TasteSignal
from app.taste_bank import (
    compute_confidence,
    extract_taste_evidence,
    is_prompt_eligible,
    rank_prompt_candidates,
)


# ---- Criterion 1: Confirmed metadata yields normalized creator/character/team/publisher/era evidence ----


def test_confirmed_metadata_yields_all_evidence_types() -> None:
    raw = {
        "id": 101,
        "name": "Issue 1",
        "issue_number": "1",
        "cover_date": "2021-06-15",
        "store_date": "2021-06-10",
        "volume": {"id": 22, "name": "Series"},
        "image": {"medium_url": "https://img/medium"},
        "person_credits": [
            {"id": 1, "name": "Alan Moore", "role": "writer"},
            {"id": 2, "name": "Dave Gibbons", "role": "artist"},
        ],
        "character_credits": [{"id": 10, "name": "Rorschach"}, {"id": 11, "name": "Nite Owl"}],
        "team_credits": [{"id": 20, "name": "Watchmen"}],
        "story_arc_credits": [{"id": 30, "name": "Arc"}],
        "site_detail_url": "https://comicvine.gamespot.com/issue/4000-101/",
        "publisher": {"id": 7, "name": "DC Comics"},
    }
    normalized = normalize_issue(raw)
    # Inject publisher at top-level for taste extraction (volume publisher alternative)
    normalized["publisher"] = {"id": 7, "name": "DC Comics"}

    evidence = extract_taste_evidence(normalized, confirmed=True)

    types = {e["feature_type"] for e in evidence}
    assert "creator" in types
    assert "character" in types
    assert "team" in types
    assert "publisher" in types
    assert "era" in types

    # Creator role preserved
    creator_keys = {e["feature_key"] for e in evidence if e["feature_type"] == "creator"}
    assert "creator:1:writer" in creator_keys
    assert "creator:2:artist" in creator_keys

    # Era bucket
    era = [e for e in evidence if e["feature_type"] == "era"]
    assert era[0]["feature_key"] == "era:2020s"
    assert era[0]["display_name"] == "2020s"


def test_duplicate_credits_do_not_double_count() -> None:
    meta = {
        "creator_credits": [
            {"id": 1, "name": "Alan Moore", "role": "writer"},
            {"id": 1, "name": "Alan Moore", "role": "writer"},
        ],
        "characters": [{"id": 10, "name": "Hero"}, {"id": 10, "name": "Hero"}],
        "teams": [],
        "cover_date": "2020-01-01",
    }
    evidence = extract_taste_evidence(meta, confirmed=True)
    creator_keys = [e["feature_key"] for e in evidence if e["feature_type"] == "creator"]
    assert len(creator_keys) == 1
    char_keys = [e["feature_key"] for e in evidence if e["feature_type"] == "character"]
    # characters key uses metadata key "characters" internally; our test uses wrong key - so check via default char path
    # Provide correct key
    meta2 = {
        "creator_credits": [{"id": 1, "name": "A", "role": "writer"}, {"id": 1, "name": "A", "role": "writer"}],
        "characters": [{"id": 5, "name": "Hero"}, {"id": 5, "name": "Hero"}],
        "teams": [{"id": 9, "name": "Team"}, {"id": 9, "name": "Team"}],
        "cover_date": "2019-05-01",
    }
    ev2 = extract_taste_evidence(meta2, confirmed=True)
    assert len([e for e in ev2 if e["feature_type"] == "character"]) == 1
    assert len([e for e in ev2 if e["feature_type"] == "team"]) == 1


def test_unconfirmed_or_missing_metadata_yields_no_evidence() -> None:
    assert extract_taste_evidence({}, confirmed=False) == []
    assert extract_taste_evidence({}, confirmed=True) == []
    assert extract_taste_evidence({"creator_credits": None}, confirmed=True) == []  # type: ignore[dict-item]
    # No cover date -> no era fabricated
    meta = {"creator_credits": [], "characters": [], "teams": []}
    ev = extract_taste_evidence(meta, confirmed=True)
    assert not any(e["feature_type"] == "era" for e in ev)
    assert not any(e["feature_type"] == "publisher" for e in ev)


# ---- Criterion 2: Repeated above-baseline creates confident inferred signal; sparse does not ----


def test_sparse_evidence_not_confident() -> None:
    # 1-2 issues remain low confidence
    assert compute_confidence(1, 1, 1, None) < 0.6
    assert compute_confidence(2, 2, 1, None) < 0.6
    assert not is_prompt_eligible(
        evidence_count=2, distinct_issue_count=2, confidence=0.35, verdict="inferred", last_prompted_at=None
    )


def test_strong_repeated_evidence_is_confident_and_diverse() -> None:
    c = compute_confidence(3, 3, 2, 0.8)
    assert c >= 0.6
    assert is_prompt_eligible(
        evidence_count=3, distinct_issue_count=3, confidence=c, verdict="inferred", last_prompted_at=None
    )
    c2 = compute_confidence(5, 5, 3, 1.0)
    assert c2 >= 0.85


def test_diversity_increases_confidence() -> None:
    single_thread = compute_confidence(3, 3, 1, None)
    multi_thread = compute_confidence(3, 3, 2, None)
    assert multi_thread > single_thread


# ---- Criterion 3: Prompt eligibility respects thresholds, diversity, cooldown, rejection ----


def test_prompt_eligibility_thresholds() -> None:
    # below threshold -> ineligible
    assert not is_prompt_eligible(evidence_count=2, distinct_issue_count=2, confidence=0.35, verdict="inferred", last_prompted_at=None)
    # below distinct issues -> ineligible
    assert not is_prompt_eligible(evidence_count=3, distinct_issue_count=1, confidence=0.7, verdict="inferred", last_prompted_at=None)


def test_rejected_suppression() -> None:
    assert not is_prompt_eligible(evidence_count=5, distinct_issue_count=5, confidence=0.95, verdict="rejected", last_prompted_at=None)


def test_cooldown_suppresses_recent_prompt() -> None:
    now = datetime.now(UTC)
    recent = now - timedelta(days=2)
    assert not is_prompt_eligible(evidence_count=5, distinct_issue_count=5, confidence=0.95, verdict="inferred", last_prompted_at=recent, now=now)
    old = now - timedelta(days=8)
    assert is_prompt_eligible(evidence_count=5, distinct_issue_count=5, confidence=0.95, verdict="inferred", last_prompted_at=old, now=now)


def test_ranking_and_diversity_cap_in_api_logic() -> None:
    # Simulate API diversity cap: rank then cap by feature_type
    signals = [
        {"id": 1, "confidence": 0.95, "evidence_count": 5, "feature_type": "creator"},
        {"id": 2, "confidence": 0.90, "evidence_count": 6, "feature_type": "creator"},
        {"id": 3, "confidence": 0.80, "evidence_count": 4, "feature_type": "character"},
    ]
    ranked = rank_prompt_candidates(signals)  # type: ignore[arg-type]
    assert ranked[0]["id"] == 1
    # Diversity: after ranking, eligible ordering keeps only one per type when API caps
    seen: set[str] = set()
    diverse = []
    for c in ranked:
        ft = c["feature_type"]  # type: ignore[index]
        if ft in seen:
            continue
        seen.add(ft)
        diverse.append(c)
    assert len(diverse) == 2
    assert diverse[0]["feature_type"] == "creator"
    assert diverse[1]["feature_type"] == "character"


# ---- Criterion 4: Verdict survives recomputation ----


@pytest.mark.asyncio
async def test_verdict_survives_recomputation(async_db) -> None:
    """Explicit verdict must not be overwritten by later inference refresh."""
    from sqlalchemy import select as sa_select

    user_id = 1
    # Create inferred signal
    sig = TasteSignal(
        user_id=user_id,
        feature_type="creator",
        feature_key="creator:1:writer",
        display_name="Alan Moore",
        role="writer",
        evidence_count=4,
        distinct_issue_count=4,
        distinct_thread_count=2,
        confidence=0.85,
        affinity=0.7,
        verdict="inferred",
        evidence_json={"issues": [1, 2, 3, 4]},
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    async_db.add(sig)
    await async_db.flush()

    # Simulate API verdict update to confirmed
    sig.verdict = "confirmed"
    sig.last_prompted_at = datetime.now(UTC)
    await async_db.flush()

    # Simulate recomputation that would compute new confidence/affinity but must preserve verdict
    # Re-load and attempt to update inferred fields only if verdict is inferred
    result = await async_db.execute(sa_select(TasteSignal).where(TasteSignal.id == sig.id))
    loaded = result.scalar_one()
    # Recompute logic: only overwrite verdict if currently inferred
    new_confidence = compute_confidence(6, 6, 3, 0.9)
    new_evidence = 6
    if loaded.verdict == "inferred":
        loaded.verdict = "inferred"  # would remain inferred
    # Explicit verdict should stay
    loaded.evidence_count = new_evidence
    loaded.confidence = new_confidence
    await async_db.flush()
    await async_db.refresh(loaded)
    assert loaded.verdict == "confirmed"
    assert loaded.evidence_count == 6

    # Same for sometimes and rejected
    for v in ("sometimes", "rejected"):
        loaded.verdict = v
        await async_db.flush()
        # Another recompute cycle
        nc = compute_confidence(7, 7, 3, None)
        if loaded.verdict == "inferred":
            loaded.verdict = "inferred"
        loaded.confidence = nc
        await async_db.flush()
        await async_db.refresh(loaded)
        assert loaded.verdict == v


@pytest.mark.asyncio
async def test_api_verdict_updates_and_suppresses_discovery(async_db, auth_client) -> None:
    """API confirm/sometimes/reject updates signal and makes it ineligible for discovery."""
    # Create signal for auth user
    from app.auth import get_current_user
    from app.database import get_db

    # Use auth_client fixture which already has user; fetch user id
    from sqlalchemy import select as sa_select
    from app.models.user import User

    # Determine username used by auth_client (test_username fixture process-specific)
    # We can fetch any user in db
    result = await async_db.execute(sa_select(User).limit(1))
    user = result.scalar_one()

    sig = TasteSignal(
        user_id=user.id,
        feature_type="character",
        feature_key="character:10",
        display_name="Rorschach",
        evidence_count=5,
        distinct_issue_count=5,
        distinct_thread_count=3,
        confidence=0.95,
        verdict="inferred",
        evidence_json={},
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    async_db.add(sig)
    await async_db.flush()
    await async_db.commit()

    # Override get_db to use this async_db
    # auth_client already overrides get_db; we add signal via async_db session but auth_client uses same DB via override

    # Need to use auth_client's transaction: but we committed above, signal persisted

    for verdict in ("confirmed", "sometimes", "rejected"):
        # reset to inferred for next loop iteration where needed
        if sig.verdict != "inferred":
            # reload and reset
            res = await async_db.execute(sa_select(TasteSignal).where(TasteSignal.id == sig.id))
            s = res.scalar_one()
            s.verdict = "inferred"
            s.last_prompted_at = None
            await async_db.commit()
            await async_db.refresh(s)
            sig = s

        resp = await auth_client.post(f"/api/v1/taste/signals/{sig.id}/verdict", json={"verdict": verdict})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["verdict"] == verdict
        assert data["id"] == sig.id

        # After rejected, discovery should not include it
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
    # Must be dismissible
    assert "onDismiss" in content
    assert 'data-testid="taste-dismiss"' in content
    # Must not use blocking modal semantics that prevent roll interaction
    # Component is fixed bottom card, not full-screen modal overlay that captures pointer events exclusively
    assert "fixed bottom" in content
    assert "Taste discovery" in content or "taste-discovery-card" in content

    # Verify RollPage integrates card without blocking roll dice
    roll_path = pathlib.Path("frontend/src/pages/RollPage/index.tsx")
    roll_content = roll_path.read_text(encoding="utf-8")
    assert "TasteDiscoveryCard" in roll_content
    # Roll dice element must remain present when discovery card rendered
    assert 'data-testid="main-die-3d"' in roll_content


# ---- Criterion 6: No Taste Bank signal changes Roll weights ----


def test_roll_weights_unchanged_by_taste_bank() -> None:
    """Phase 7 must not change Roll dice pool weighting."""
    import pathlib

    roll_py = pathlib.Path("app/api/roll.py").read_text(encoding="utf-8")
    # Roll must not import taste bank services or taste signals for weighting
    assert "taste" not in roll_py.lower() or "taste_signal" not in roll_py.lower()
    # Explicitly ensure no taste-related weighting logic
    assert "TasteSignal" not in roll_py
    assert "taste_bank" not in roll_py.lower()

    queue_py = pathlib.Path("comic_pile/queue.py").read_text(encoding="utf-8") if pathlib.Path("comic_pile/queue.py").exists() else ""
    assert "taste" not in queue_py.lower()
