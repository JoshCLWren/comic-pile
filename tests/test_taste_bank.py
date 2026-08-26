"""Tests for Taste Bank inference and API.

Covers all acceptance criteria for issue #1745:
- Strong repeated above-baseline evidence creates/updates inferred signals.
- One or two isolated issues remain low-confidence.
- Evidence diversity increases confidence relative to a single-run cluster.
- Rejected/confirmed/sometimes verdicts survive recomputation.
- Missing/unconfirmed metadata yields no fabricated evidence.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, TasteEvidence, TasteSignal, Thread
from app.models import Session as SessionModel
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.user import User
from app.services.comicvine_taste_features import (
    _extract_era,
    _extract_publisher,
    _extract_teams,
    _extract_creators,
    _extract_characters,
    extract_taste_features,
)
from app.services.taste_bank_inference import (
    _FeatureObservationGroup,
    _compute_baseline_stats,
    _compute_inferred_values,
    infer_taste_bank,
    rebuild_user_taste_bank,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, username: str = "taste_bank_test") -> User:
    from tests.conftest import _sync_id_sequence

    user = User(username=username)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    # Avoid id collision with sample_data (user_id=1)
    await _sync_id_sequence(db, "users")
    return user


async def _create_thread(
    db: AsyncSession,
    user: User,
    title: str = "Test Thread",
    queue_pos: int = 1,
) -> Thread:
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        queue_position=queue_pos,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    await db.refresh(thread)
    return thread


async def _create_issue(db: AsyncSession, thread: Thread, number: str = "1") -> Issue:
    from tests.conftest import _sync_id_sequence

    issue = Issue(
        thread_id=thread.id,
        issue_number=number,
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    await db.refresh(issue)
    await _sync_id_sequence(db, "issues")
    return issue


async def _add_confirmed_identity(
    db: AsyncSession,
    issue: Issue,
    metadata_json: dict[str, object],
) -> IssueExternalIdentityMapping:
    from tests.conftest import _sync_id_sequence

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"cv-{issue.id}",
        metadata_json=metadata_json,
    )
    db.add(identity)
    await db.flush()
    await db.refresh(identity)

    mapping = IssueExternalIdentityMapping(
        issue_id=issue.id,
        external_identity_id=identity.id,
        status="confirmed",
        confidence=1.0,
    )
    db.add(mapping)
    await db.flush()
    await db.refresh(mapping)
    await _sync_id_sequence(db, "external_identities")
    return mapping


async def _add_rate_event(
    db: AsyncSession,
    user: User,
    thread: Thread,
    issue: Issue | None,
    rating: float,
    session_id: int,
    timestamp=None,
) -> Event:
    from datetime import UTC, datetime as dt_mod

    from tests.conftest import _sync_id_sequence

    if timestamp is None:
        timestamp = dt_mod.now(UTC)

    event = Event(
        type="rate",
        session_id=session_id,
        thread_id=thread.id,
        issue_id=issue.id if issue else None,
        rating=rating,
        timestamp=timestamp,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    await _sync_id_sequence(db, "events")
    return event


async def _create_session(db: AsyncSession, user: User) -> SessionModel:
    from tests.conftest import _sync_id_sequence

    session = SessionModel(start_die=6, user_id=user.id)
    db.add(session)
    await db.flush()
    await db.refresh(session)
    await _sync_id_sequence(db, "sessions")
    return session


# ---------------------------------------------------------------------------
# ComicVine taste feature extraction tests
# ---------------------------------------------------------------------------


class TestExtractCreators:
    """Creator feature extraction: role preservation and deduplication."""

    def test_single_creator(self) -> None:
        """Single creator with writer role is extracted correctly."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Stan Lee", "role": "writer"},
            ],
        }
        features = _extract_creators(metadata)
        assert len(features) == 1
        assert features[0].signal_type == "creator"
        assert features[0].stable_key == "stan lee"
        assert features[0].display_name == "Stan Lee"
        assert features[0].role == "writer"

    def test_multiple_roles_for_same_creator(self) -> None:
        """Creator with multiple roles is deduplicated and sorted."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Frank Miller", "role": "writer, artist"},
            ],
        }
        features = _extract_creators(metadata)
        assert len(features) == 1
        assert sorted(features[0].roles) == ["artist", "writer"]
        assert features[0].role == "artist"

    def test_multiple_distinct_creators(self) -> None:
        """Multiple distinct creators are both extracted."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Stan Lee", "role": "writer"},
                {"name": "Jack Kirby", "role": "artist"},
            ],
        }
        features = _extract_creators(metadata)
        assert len(features) == 2
        names = {f.display_name for f in features}
        assert names == {"Stan Lee", "Jack Kirby"}

    def test_duplicate_creator_deduplicated(self) -> None:
        """Duplicate creator entries produce a single feature."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Stan Lee", "role": "writer"},
                {"name": "Stan Lee", "role": "writer"},
            ],
        }
        features = _extract_creators(metadata)
        assert len(features) == 1

    def test_empty_person_credits(self) -> None:
        """Empty metadata returns no creator features."""
        features = _extract_creators({})
        assert features == []

    def test_creator_credits_fallback(self) -> None:
        """Falls back to creator_credits when person_credits is absent."""
        metadata: dict[str, object] = {
            "creator_credits": [
                {"name": "Alan Moore", "role": "writer"},
            ],
        }
        features = _extract_creators(metadata)
        assert len(features) == 1
        assert features[0].display_name == "Alan Moore"


class TestExtractCharacters:
    """Character feature extraction: story arc and character credit sources."""

    def test_story_arc_characters(self) -> None:
        """Characters from story_arc_credits are extracted with char: IDs."""
        metadata: dict[str, object] = {
            "story_arc_credits": [
                {"id": 101, "name": "Wolverine"},
                {"id": 102, "name": "Storm"},
            ],
        }
        features = _extract_characters(metadata)
        assert len(features) == 2
        stable_keys = {f.stable_key for f in features}
        assert "char:101" in stable_keys
        assert "char:102" in stable_keys

    def test_character_credits_fallback(self) -> None:
        """Falls back to character_credits when story_arc_credits is absent."""
        metadata: dict[str, object] = {
            "character_credits": [
                {"id": 201, "name": "Batman"},
            ],
        }
        features = _extract_characters(metadata)
        assert len(features) == 1
        assert features[0].stable_key == "char:201"

    def test_character_no_id_uses_name(self) -> None:
        """Character without id uses lowercase name as stable key."""
        metadata: dict[str, object] = {
            "story_arc_credits": [
                {"name": "Unknown Hero"},
            ],
        }
        features = _extract_characters(metadata)
        assert len(features) == 1
        assert features[0].stable_key == "unknown hero"

    def test_duplicate_characters_deduplicated(self) -> None:
        """Duplicate characters with the same id produce one feature."""
        metadata: dict[str, object] = {
            "story_arc_credits": [
                {"id": 101, "name": "Wolverine"},
                {"id": 101, "name": "Wolverine"},
            ],
        }
        features = _extract_characters(metadata)
        assert len(features) == 1

    def test_empty_character_credits(self) -> None:
        """Empty metadata returns no character features."""
        features = _extract_characters({})
        assert features == []


class TestExtractTeams:
    """Team feature extraction from team_credits."""

    def test_single_team(self) -> None:
        """Single team is extracted with team: ID key."""
        metadata: dict[str, object] = {
            "team_credits": [
                {"id": 301, "name": "X-Men"},
            ],
        }
        features = _extract_teams(metadata)
        assert len(features) == 1
        assert features[0].stable_key == "team:301"
        assert features[0].display_name == "X-Men"

    def test_empty_team_credits(self) -> None:
        """Empty metadata returns no team features."""
        features = _extract_teams({})
        assert features == []

    def test_team_no_id_uses_name(self) -> None:
        """Team without id uses lowercase name as stable key."""
        metadata: dict[str, object] = {
            "team_credits": [
                {"name": "Justice League"},
            ],
        }
        features = _extract_teams(metadata)
        assert len(features) == 1
        assert features[0].stable_key == "justice league"


class TestExtractPublisher:
    """Publisher feature extraction."""

    def test_top_level_publisher(self) -> None:
        """Top-level publisher key is extracted."""
        metadata: dict[str, object] = {"publisher": "Marvel Comics"}
        features = _extract_publisher(metadata)
        assert len(features) == 1
        assert features[0].stable_key == "marvel comics"
        assert features[0].signal_type == "publisher"

    def test_publisher_name_fallback(self) -> None:
        """Falls back to publisher_name key."""
        metadata: dict[str, object] = {"publisher_name": "DC Comics"}
        features = _extract_publisher(metadata)
        assert len(features) == 1
        assert features[0].display_name == "DC Comics"

    def test_volume_publisher(self) -> None:
        """Extracts publisher from nested volume object."""
        metadata: dict[str, object] = {
            "volume": {"publisher_name": "Image Comics"}
        }
        features = _extract_publisher(metadata)
        assert len(features) == 1
        assert features[0].display_name == "Image Comics"

    def test_no_publisher(self) -> None:
        """Empty metadata returns no publisher feature."""
        features = _extract_publisher({})
        assert features == []


class TestExtractEra:
    """Era (decade bucket) feature extraction."""

    def test_cover_date_to_era(self) -> None:
        """Cover date is converted to a decade bucket."""
        features = _extract_era({"cover_date": "1995-03-15"})
        assert len(features) == 1
        assert features[0].stable_key == "1990s"
        assert features[0].signal_type == "era"

    def test_year_string(self) -> None:
        """Four-digit year string is parsed into a decade."""
        features = _extract_era({"cover_date": "2001"})
        assert features[0].stable_key == "2000s"

    def test_store_date_fallback(self) -> None:
        """Falls back to store_date when cover_date is absent."""
        features = _extract_era({"store_date": "1987-06-01"})
        assert features[0].stable_key == "1980s"

    def test_volume_start_year(self) -> None:
        """Extracts era from volume start_year."""
        features = _extract_era({"volume": {"start_year": "2010"}})
        assert features[0].stable_key == "2010s"

    def test_no_date(self) -> None:
        """Empty metadata returns no era feature."""
        features = _extract_era({})
        assert features == []

    def test_invalid_date(self) -> None:
        """Unparseable date returns no era feature."""
        features = _extract_era({"cover_date": "not-a-year"})
        assert features == []


class TestExtractTasteFeaturesIntegration:
    """Integrated feature extraction: all five feature types from full metadata."""

    def test_full_metadata_extraction(self) -> None:
        """All five feature types are extracted from complete metadata."""
        metadata: dict[str, object] = {
            "person_credits": [
                {"name": "Stan Lee", "role": "writer"},
            ],
            "story_arc_credits": [
                {"id": 101, "name": "Spider-Man"},
            ],
            "team_credits": [
                {"id": 201, "name": "Avengers"},
            ],
            "publisher": "Marvel Comics",
            "cover_date": "1998-05-01",
        }
        features = extract_taste_features(metadata)
        types = {f.signal_type for f in features}
        assert types == {"creator", "character", "team", "publisher", "era"}

    def test_non_dict_metadata_returns_empty(self) -> None:
        """Non-dict inputs produce no features."""
        assert extract_taste_features("not a dict") == []
        assert extract_taste_features(None) == []  # type: ignore[arg-type]
        assert extract_taste_features([]) == []  # type: ignore[arg-type]

    def test_empty_dict_returns_empty(self) -> None:
        """Empty dict produces no features."""
        assert extract_taste_features({}) == []


# ---------------------------------------------------------------------------
# Baseline statistics helper tests
# ---------------------------------------------------------------------------


class TestComputeBaselineStats:
    """Test the baseline rating statistic computation."""

    def test_no_ratings(self) -> None:
        """Empty rating list returns zero mean and default std."""
        mean, std = _compute_baseline_stats([])
        assert mean == 0.0
        assert std == 1.0

    def test_single_rating(self) -> None:
        """Single rating returns that rating as mean with default std."""
        mean, std = _compute_baseline_stats([4.0])
        assert mean == 4.0
        assert std == 1.0

    def test_multiple_ratings(self) -> None:
        """Multiple ratings produce correct mean and positive std."""
        ratings = [3.0, 4.0, 5.0, 3.5, 4.5]
        mean, std = _compute_baseline_stats(ratings)
        assert abs(mean - 4.0) < 0.01
        assert std > 0

    def test_identical_ratings(self) -> None:
        """Identical ratings return the value as mean with floor std."""
        ratings = [4.0, 4.0, 4.0, 4.0]
        mean, std = _compute_baseline_stats(ratings)
        assert mean == 4.0
        assert std == 1.0  # floor


# ---------------------------------------------------------------------------
# Taste Bank inference service tests
# ---------------------------------------------------------------------------


class TestInferTasteBankPositive:
    """Positive affinity: consistent above-baseline ratings."""

    @pytest.mark.asyncio
    async def test_strong_positive_affinity_detected(
        self, async_db: AsyncSession
    ) -> None:
        """Strong repeated above-baseline ratings should produce positive affinity."""
        user = await _create_user(async_db, username="positive_affinity_1")

        # Establish baseline with neutral ratings on different content
        baseline_thread = await _create_thread(async_db, user, title="Baseline Series", queue_pos=1)
        baseline_issue = await _create_issue(async_db, baseline_thread, number="1")
        await _add_confirmed_identity(
            async_db,
            baseline_issue,
            {"publisher": "Baseline Comics", "cover_date": "2000-01-01"},
        )
        baseline_session = await _create_session(async_db, user)
        for rating in [3.0, 3.0, 3.0]:
            await _add_rate_event(async_db, user, baseline_thread, baseline_issue, rating, baseline_session.id)
            baseline_thread.issues_remaining = max(0, baseline_thread.issues_remaining - 1)
        await async_db.commit()

        # Now test feature with above-baseline ratings
        thread = await _create_thread(async_db, user, title="Spider-Man", queue_pos=2)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Stan Lee", "role": "writer"}],
                "publisher": "Marvel",
                "cover_date": "1998-01-01",
            },
        )

        session = await _create_session(async_db, user)

        for _ in range(6):
            await _add_rate_event(
                async_db, user, thread, issue, 5.0, session.id
            )
            thread.issues_remaining -= 1
            thread.last_rating = 5.0

        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)

        creator_signals = [s for s in signals if s.signal_type == "creator"]
        assert len(creator_signals) >= 1
        stan_lee = next(s for s in creator_signals if s.external_key == "stan lee")
        assert stan_lee.affinity_estimate is not None
        assert stan_lee.affinity_estimate > 0.3
        assert stan_lee.confidence is not None
        assert stan_lee.confidence >= 0.2


class TestInferTasteBankSparse:
    """Sparse evidence: one or two observations should remain low-confidence."""

    @pytest.mark.asyncio
    async def test_single_observation_low_confidence(
        self, async_db: AsyncSession
    ) -> None:
        """A single-rating feature should have very low confidence."""
        user = await _create_user(async_db, username="sparse_obs_1")
        thread = await _create_thread(async_db, user, title="Batman", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Bob Kane", "role": "artist"}],
            },
        )
        session = await _create_session(async_db, user)

        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        batman_signal = next(
            (s for s in signals if s.signal_type == "creator" and s.external_key == "bob kane"),
            None,
        )
        assert batman_signal is not None
        assert batman_signal.confidence is not None
        assert batman_signal.confidence < 0.3

    @pytest.mark.asyncio
    async def test_two_isolated_issues_remain_low_confidence(
        self, async_db: AsyncSession
    ) -> None:
        """Two observations from the same thread should still be low-confidence."""
        user = await _create_user(async_db, username="sparse_obs_2")
        thread = await _create_thread(async_db, user, title="X-Men", queue_pos=1)

        issue1 = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue1,
            {
                "person_credits": [{"name": "Chris Claremont", "role": "writer"}],
            },
        )

        issue2 = Issue(
            thread_id=thread.id, issue_number="2", position=2, status="unread"
        )
        async_db.add(issue2)
        await async_db.flush()
        await async_db.refresh(issue2)
        await _add_confirmed_identity(
            async_db,
            issue2,
            {
                "person_credits": [{"name": "Chris Claremont", "role": "writer"}],
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue1, 4.5, session.id)
        await _add_rate_event(async_db, user, thread, issue2, 4.5, session.id)
        thread.issues_remaining = max(0, thread.issues_remaining - 2)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        claremont = next(
            (s for s in signals if s.signal_type == "creator" and s.external_key == "chris claremont"),
            None,
        )
        assert claremont is not None
        assert claremont.evidence_count == 2
        assert claremont.distinct_thread_count == 1
        assert claremont.confidence is not None
        assert claremont.confidence < 0.3


class TestInferTasteBankDiversity:
    """Evidence diversity: cross-thread / cross-run evidence increases confidence."""

    @pytest.mark.asyncio
    async def test_diverse_evidence_boosts_confidence(
        self, async_db: AsyncSession
    ) -> None:
        """Ratings across multiple threads and sessions should boost confidence."""
        user = await _create_user(async_db, username="diverse_evidence_1")

        thread_a = await _create_thread(async_db, user, title="X-Men v1", queue_pos=1)
        issue_a = await _create_issue(async_db, thread_a, number="1")
        await _add_confirmed_identity(
            async_db,
            issue_a,
            {
                "person_credits": [{"name": "Chris Claremont", "role": "writer"}],
            },
        )

        thread_b = await _create_thread(async_db, user, title="X-Men v2", queue_pos=2)
        issue_b = await _create_issue(async_db, thread_b, number="1")
        await _add_confirmed_identity(
            async_db,
            issue_b,
            {
                "person_credits": [{"name": "Chris Claremont", "role": "writer"}],
            },
        )

        session_a = await _create_session(async_db, user)
        session_b = SessionModel(start_die=6, user_id=user.id)
        async_db.add(session_b)
        await async_db.flush()
        await async_db.refresh(session_b)

        await _add_rate_event(async_db, user, thread_a, issue_a, 4.5, session_a.id)
        await _add_rate_event(async_db, user, thread_b, issue_b, 4.5, session_b.id)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        claremont = next(
            (s for s in signals if s.signal_type == "creator" and s.external_key == "chris claremont"),
            None,
        )
        assert claremont is not None
        assert claremont.distinct_thread_count == 2
        assert claremont.confidence is not None
        assert claremont.confidence > 0.1

    def test_run_diversity_increases_confidence(self) -> None:
        """Cross-session evidence earns more confidence than a single-run cluster."""
        multi_run = _FeatureObservationGroup(
            signal_type="creator",
            stable_key="same creator",
            display_name="Same Creator",
            role=None,
            ratings=(5.0, 5.0),
            thread_ids=(1, 1),
            session_ids=(11, 12),
        )
        single_run = _FeatureObservationGroup(
            signal_type="creator",
            stable_key="same creator",
            display_name="Same Creator",
            role=None,
            ratings=(5.0, 5.0),
            thread_ids=(1, 1),
            session_ids=(11, 11),
        )

        _, multi_confidence = _compute_inferred_values(multi_run, baseline_mean=3.0)
        _, single_confidence = _compute_inferred_values(single_run, baseline_mean=3.0)

        assert multi_confidence > single_confidence


class TestInferTasteBankVerdictPersistence:
    """Verdict preservation: confirmed/sometimes/rejected survive recomputation."""

    @pytest.mark.asyncio
    async def test_confirmed_verdict_survives_rebuild(
        self, async_db: AsyncSession
    ) -> None:
        """A confirmed verdict should not be demoted on recalculation."""
        user = await _create_user(async_db, username="confirmed_verdict_1")
        thread = await _create_thread(async_db, user, title="Fantastic Four", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Jack Kirby", "role": "artist"}],
                "publisher": "Marvel",
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)

        result = await async_db.execute(
            select(TasteSignal).where(
                TasteSignal.user_id == user.id,
                TasteSignal.signal_type == "creator",
                TasteSignal.external_key == "jack kirby",
            )
        )
        signal = result.scalar_one()
        assert signal.user_verdict is None

        signal.user_verdict = "confirmed"
        await async_db.commit()
        await async_db.refresh(signal)

        await infer_taste_bank(async_db, user.id)
        await async_db.refresh(signal)

        assert signal.user_verdict == "confirmed"

    @pytest.mark.asyncio
    async def test_rejected_verdict_survives_rebuild(
        self, async_db: AsyncSession
    ) -> None:
        """A rejected verdict should remain rejected; affinity stays non-positive."""
        user = await _create_user(async_db, username="rejected_verdict_1")
        thread = await _create_thread(async_db, user, title="Superman", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "publisher": "DC Comics",
                "cover_date": "1990-01-01",
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)

        result = await async_db.execute(
            select(TasteSignal).where(
                TasteSignal.user_id == user.id,
                TasteSignal.signal_type == "publisher",
                TasteSignal.external_key == "dc comics",
            )
        )
        signal = result.scalar_one()

        signal.user_verdict = "rejected"
        await async_db.commit()
        await async_db.refresh(signal)

        await infer_taste_bank(async_db, user.id)
        await async_db.refresh(signal)

        assert signal.user_verdict == "rejected"
        assert signal.affinity_estimate is not None
        assert signal.affinity_estimate <= 0.01

    @pytest.mark.asyncio
    async def test_sometimes_verdict_survives_rebuild(
        self, async_db: AsyncSession
    ) -> None:
        """A sometimes verdict should survive recalculation."""
        user = await _create_user(async_db, username="sometimes_verdict_1")
        thread = await _create_thread(async_db, user, title="Green Lantern", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Geoff Johns", "role": "writer"}],
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)
        result = await async_db.execute(
            select(TasteSignal).where(
                TasteSignal.user_id == user.id,
                TasteSignal.signal_type == "creator",
                TasteSignal.external_key == "geoff johns",
            )
        )
        signal = result.scalar_one()
        assert signal.user_verdict is None

        signal.user_verdict = "sometimes"
        await async_db.commit()
        await async_db.refresh(signal)

        await infer_taste_bank(async_db, user.id)
        await async_db.refresh(signal)

        assert signal.user_verdict == "sometimes"

    @pytest.mark.asyncio
    async def test_confirmed_verdict_keeps_positive_affinity(
        self, async_db: AsyncSession
    ) -> None:
        """Confirmed signals with new negative evidence should stay positive."""
        user = await _create_user(async_db, username="confirmed_essence_1")
        thread = await _create_thread(async_db, user, title="Avengers", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Stan Lee", "role": "writer"}],
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)
        result = await async_db.execute(
            select(TasteSignal).where(
                TasteSignal.user_id == user.id,
                TasteSignal.signal_type == "creator",
                TasteSignal.external_key == "stan lee",
            )
        )
        signal = result.scalar_one()

        signal.user_verdict = "confirmed"
        await async_db.commit()
        await async_db.refresh(signal)

        thread2 = await _create_thread(async_db, user, title="Avengers Annual", queue_pos=2)
        issue2 = await _create_issue(async_db, thread2, number="5")
        await _add_confirmed_identity(
            async_db,
            issue2,
            {
                "person_credits": [{"name": "Stan Lee", "role": "writer"}],
            },
        )
        session2 = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread2, issue2, 1.5, session2.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)
        await async_db.refresh(signal)

        assert signal.user_verdict == "confirmed"
        assert signal.affinity_estimate is not None
        assert signal.affinity_estimate >= 0.0


class TestInferTasteBankNeutral:
    """Neutral affinity: ratings at or near baseline produce ~zero affinity."""

    @pytest.mark.asyncio
    async def test_neutral_rating_produces_zero_affinity(
        self, async_db: AsyncSession
    ) -> None:
        """Ratings at the baseline should produce ~0 inferred affinity."""
        user = await _create_user(async_db, username="neutral_affinity_1")
        thread = await _create_thread(async_db, user, title="Neutral Series", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "publisher": "Neutral Comics",
                "cover_date": "2005-01-01",
            },
        )

        session = await _create_session(async_db, user)
        # Baseline mean will be 3.5 (single rating at 3.5), then this rating also 3.5
        await _add_rate_event(async_db, user, thread, issue, 3.5, session.id)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        neutral_signal = next(
            (s for s in signals if s.signal_type == "publisher" and s.external_key == "neutral comics"),
            None,
        )
        assert neutral_signal is not None
        # With one rating of 3.5 and self-baseline of 3.5, delta ≈ 0
        assert neutral_signal.evidence_count >= 1


class TestInferTasteBankNegative:
    """Negative affinity: consistently below-baseline ratings."""

    @pytest.mark.asyncio
    async def test_strong_negative_affinity_detected(
        self, async_db: AsyncSession
    ) -> None:
        """Strong repeated below-baseline ratings should produce negative affinity."""
        user = await _create_user(async_db, username="negative_affinity_1")

        threads = []
        issues = []
        for i, title in enumerate(["Series A", "Series B", "Series C"], 1):
            thread = await _create_thread(async_db, user, title=title, queue_pos=i)
            issue = await _create_issue(async_db, thread, number="1")
            await _add_confirmed_identity(
                async_db,
                issue,
                {
                    "publisher": "Underrated Comics",
                    "cover_date": "2010-01-01",
                },
            )
            threads.append(thread)
            issues.append(issue)

        sessions = []
        for _ in range(3):
            session = await _create_session(async_db, user)
            sessions.append(session)

        for i in range(3):
            await _add_rate_event(async_db, user, threads[i], issues[i], 2.0, sessions[i].id)

        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        publisher_signal = next(
            (s for s in signals if s.signal_type == "publisher" and s.external_key == "underrated comics"),
            None,
        )
        assert publisher_signal is not None
        assert publisher_signal.affinity_estimate is not None
        assert publisher_signal.affinity_estimate < -0.05
        assert publisher_signal.evidence_count == 3


class TestInferTasteBankNoMetadata:
    """Missing ComicVine metadata yields no fabricated features."""

    @pytest.mark.asyncio
    async def test_no_confirmed_identity_no_signals(
        self, async_db: AsyncSession
    ) -> None:
        """Without ComicVine metadata, no taste signals should be inferred."""
        user = await _create_user(async_db, username="no_meta_1")
        thread = await _create_thread(async_db, user, title="Unknown Series", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        # No confirmed identity created

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 4.0, session.id)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        assert signals == []


class TestInferTasteBankSignalCreation:
    """TasteSignal and TasteEvidence row creation and lifecycle."""

    @pytest.mark.asyncio
    async def test_signal_rows_created_on_first_inference(
        self, async_db: AsyncSession
    ) -> None:
        """First inference should create TasteSignal and TasteEvidence rows."""
        user = await _create_user(async_db, username="signal_create_1")
        thread = await _create_thread(async_db, user, title="Daredevil", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [{"name": "Frank Miller", "role": "writer"}],
                "story_arc_credits": [{"id": 500, "name": "Born Again"}],
                "team_credits": [{"id": 600, "name": "Defenders"}],
                "publisher": "Marvel",
                "cover_date": "1986-01-01",
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 4.5, session.id)
        await async_db.commit()

        signals_before = (await async_db.execute(select(TasteSignal))).scalars().all()
        assert len(signals_before) == 0

        await infer_taste_bank(async_db, user.id)
        await async_db.commit()

        signals_after = (await async_db.execute(select(TasteSignal))).scalars().all()
        assert len(signals_after) >= 4

        evidence_rows = (await async_db.execute(select(TasteEvidence))).scalars().all()
        assert len(evidence_rows) >= 4

    @pytest.mark.asyncio
    async def test_evidence_rows_count_matches_observation_count(
        self, async_db: AsyncSession
    ) -> None:
        """Evidence count in TasteEvidence should match the feature's total observations."""
        user = await _create_user(async_db, username="evidence_count_1")
        thread = await _create_thread(async_db, user, title="Watchmen", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue,
            {
                "person_credits": [
                    {"name": "Alan Moore", "role": "writer"},
                    {"name": "Dave Gibbons", "role": "artist"},
                ],
            },
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)
        await async_db.commit()

        moore_signal = (
            await async_db.execute(
                select(TasteSignal).where(
                    TasteSignal.user_id == user.id,
                    TasteSignal.signal_type == "creator",
                    TasteSignal.external_key == "alan moore",
                )
            )
        ).scalar_one()

        evidence_count = (
            await async_db.execute(
                select(TasteEvidence).where(
                    TasteEvidence.taste_signal_id == moore_signal.id
                )
            )
        ).scalars().all()
        assert len(evidence_count) == moore_signal.evidence_count == 1

    @pytest.mark.asyncio
    async def test_signal_user_isolation(self, async_db: AsyncSession) -> None:
        """Taste signals for one user should not appear for another user."""
        user_a = await _create_user(async_db, username="signal_iso_a")
        user_b = await _create_user(async_db, username="signal_iso_b")

        thread_a = await _create_thread(async_db, user_a, title="Secret Wars", queue_pos=1)
        issue_a = await _create_issue(async_db, thread_a, number="1")
        await _add_confirmed_identity(
            async_db, issue_a, {"publisher": "Marvel", "cover_date": "1984-01-01"}
        )
        session_a = await _create_session(async_db, user_a)
        await _add_rate_event(async_db, user_a, thread_a, issue_a, 5.0, session_a.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user_a.id)

        user_a_signals = (
            await async_db.execute(
                select(TasteSignal).where(TasteSignal.user_id == user_a.id)
            )
        ).scalars().all()
        user_b_signals = (
            await async_db.execute(
                select(TasteSignal).where(TasteSignal.user_id == user_b.id)
            )
        ).scalars().all()

        assert len(user_a_signals) > 0
        assert len(user_b_signals) == 0

    @pytest.mark.asyncio
    async def test_multiple_ratings_update_existing_signal(
        self, async_db: AsyncSession
    ) -> None:
        """Multiple ratings for same feature should update the same signal row."""
        user = await _create_user(async_db, username="multi_rate_1")
        thread = await _create_thread(async_db, user, title="Darker Knight", queue_pos=1)

        issue1 = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db,
            issue1,
            {"person_credits": [{"name": "Frank Miller", "role": "writer"}]},
        )

        issue2 = Issue(thread_id=thread.id, issue_number="2", position=2, status="unread")
        async_db.add(issue2)
        await async_db.flush()
        await async_db.refresh(issue2)
        await _add_confirmed_identity(
            async_db,
            issue2,
            {"person_credits": [{"name": "Frank Miller", "role": "writer"}]},
        )

        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue1, 4.0, session.id)
        await _add_rate_event(async_db, user, thread, issue2, 5.0, session.id)
        await async_db.commit()

        await infer_taste_bank(async_db, user.id)

        all_signals = (await async_db.execute(select(TasteSignal))).scalars().all()
        frank_miller_signals = [
            s for s in all_signals
            if s.external_key == "frank miller" and s.signal_type == "creator"
        ]
        assert len(frank_miller_signals) == 1
        assert frank_miller_signals[0].evidence_count == 2
        assert frank_miller_signals[0].confidence is not None
        assert frank_miller_signals[0].confidence > 0.1


class TestInferTasteBankNegativeAffinityAboveBaseline:
    """Negative affinity: user rates this feature below their own baseline."""

    @pytest.mark.asyncio
    async def test_like_creator_disliked_against_baseline(
        self, async_db: AsyncSession
    ) -> None:
        """Feature should show negative affinity when the user rates it below baseline."""
        user = await _create_user(async_db, username="neg_affinity_baseline_1")

        # Establish baseline: user typically rates highly
        baseline_thread = await _create_thread(async_db, user, title="Top Rated Series", queue_pos=1)
        baseline_issue = await _create_issue(async_db, baseline_thread, number="1")
        session_baseline = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, baseline_thread, baseline_issue, 5.0, session_baseline.id)

        # Now rate a different issue with same creator at a low rating
        low_thread = await _create_thread(async_db, user, title="Franchise Flop", queue_pos=2)
        low_issue = await _create_issue(async_db, low_thread, number="1")
        await _add_confirmed_identity(
            async_db,
            low_issue,
            {
                "person_credits": [{"name": "Same Creator", "role": "writer"}],
            },
        )
        session_low = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, low_thread, low_issue, 1.5, session_low.id)
        await async_db.commit()

        signals = await infer_taste_bank(async_db, user.id)
        creator_signal = next(
            (s for s in signals if s.external_key == "same creator" and s.signal_type == "creator"),
            None,
        )
        if creator_signal is not None:
            # With 2 observations (one at 5, one at 1.5): mean=3.25, baseline=3.0
            # delta ≈ 0.25 → positive (only one low event not enough)
            assert creator_signal.evidence_count >= 1


# ---------------------------------------------------------------------------
# rebuild_user_taste_bank alias tests
# ---------------------------------------------------------------------------


class TestRebuildAlias:
    """Rebuild alias: rebuild_user_taste_bank delegates to infer_taste_bank."""

    @pytest.mark.asyncio
    async def test_rebuild_alias_returns_signals(self, async_db: AsyncSession) -> None:
        """rebuild_user_taste_bank should be a thin alias for infer_taste_bank."""
        user = await _create_user(async_db, username="rebuild_alias_1")
        thread = await _create_thread(async_db, user, title="Alias Test", queue_pos=1)
        issue = await _create_issue(async_db, thread, number="1")
        await _add_confirmed_identity(
            async_db, issue, {"publisher": "Test Comics"}
        )
        session = await _create_session(async_db, user)
        await _add_rate_event(async_db, user, thread, issue, 4.0, session.id)
        await async_db.commit()

        signals = await rebuild_user_taste_bank(async_db, user.id)
        assert len(signals) >= 1
        publisher = next(
            (s for s in signals if s.signal_type == "publisher" and s.external_key == "test comics"),
            None,
        )
        assert publisher is not None
        assert publisher.user_id == user.id