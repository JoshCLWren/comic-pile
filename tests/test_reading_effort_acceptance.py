"""Phase 1 acceptance regression for the reading-effort model.

Seeds linked roll -> rate histories containing valid reads, instant-marking
noise, an extreme long-duration outlier, sparse issue history, sufficient
thread history, and a new comic with confirmed publication-era metadata, then
verifies every acceptance criterion from issue #1705:

- invalid duration observations are excluded with documented reasons;
- sufficient history produces robust observed effort;
- sparse issue history falls back safely to thread history;
- missing observed history falls back to the publication era;
- observed history takes precedence over the era prior;
- roll events record the decision-time estimate/source;
- legacy random Roll selection behavior is unchanged.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    Event,
    ExternalIdentity,
    Issue,
    Thread,
    ThreadExternalSeriesMapping,
    User,
)
from app.services.reading_effort import (
    ERA_PRIOR_CONFIDENCE,
    MAX_VALID_READ_SECONDS,
    MIN_OBSERVED_SAMPLES,
    MIN_VALID_READ_SECONDS,
    RECOMMENDATION_CONTEXT_VERSION,
    EstimateSource,
    ExclusionReason,
    aggregate_observations,
    classify_observation,
    collect_classified_observations,
    compute_effort_estimate,
)

pytestmark = pytest.mark.asyncio


async def _ensure_user(db) -> int:
    """Create a fresh user and return its id."""
    user = User(username="reading-effort-acceptance", created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user.id


async def _add_thread(
    db,
    user_id: int,
    title: str,
    *,
    queue_position: int = 1,
    status: str = "active",
    issues_remaining: int = 5,
    is_blocked: bool = False,
) -> Thread:
    """Create one reading thread for the given user."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=issues_remaining,
        queue_position=queue_position,
        status=status,
        user_id=user_id,
        created_at=datetime.now(UTC),
        is_blocked=is_blocked,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _add_issue(db, thread: Thread, number: int) -> Issue:
    """Create a minimal unread issue row for event foreign keys."""
    issue = Issue(
        thread_id=thread.id,
        issue_number=str(number),
        position=number,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    return issue


async def _link_read(
    db,
    thread: Thread,
    *,
    minutes: float,
    rolled_at: datetime,
    issue: Issue | None = None,
) -> tuple[Event, Event]:
    """Seed one linked roll -> rate observation after ``minutes`` of reading."""
    roll_event = Event(
        type="roll",
        selected_thread_id=thread.id,
        die=6,
        result=1,
        selection_method="random",
        timestamp=rolled_at,
    )
    db.add(roll_event)
    await db.flush()
    rate_event = Event(
        type="rate",
        thread_id=thread.id,
        source_roll_event_id=roll_event.id,
        rating=4.0,
        issues_read=1,
        die=6,
        die_after=8,
        issue_id=issue.id if issue is not None else None,
        issue_number=str(issue.issue_number) if issue is not None else None,
        timestamp=rolled_at + timedelta(minutes=minutes),
    )
    db.add(rate_event)
    await db.flush()
    return roll_event, rate_event


async def _confirm_series_metadata(db, thread: Thread, cover_date: str) -> None:
    """Attach confirmed ComicVine series metadata carrying a cover date."""
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
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await db.flush()


def test_invalid_duration_observations_excluded_with_documented_reasons():
    """Every out-of-bounds duration maps to its documented exclusion reason."""
    assert classify_observation(None) == (False, ExclusionReason.MISSING_LINK)
    assert classify_observation(0.0) == (False, ExclusionReason.NON_POSITIVE)
    assert classify_observation(-30.0) == (False, ExclusionReason.NON_POSITIVE)
    assert classify_observation(MIN_VALID_READ_SECONDS - 1) == (
        False,
        ExclusionReason.TOO_SHORT,
    )
    outlier_seconds = MAX_VALID_READ_SECONDS + 1
    assert classify_observation(outlier_seconds) == (False, ExclusionReason.TOO_LONG)
    assert ExclusionReason.MISSING_LINK == "unlinked"
    assert ExclusionReason.NON_POSITIVE == "non_positive"
    assert ExclusionReason.TOO_SHORT == "too_short"
    assert ExclusionReason.TOO_LONG == "too_long"
    # Inclusive validity boundaries.
    assert classify_observation(float(MIN_VALID_READ_SECONDS)) == (True, None)
    assert classify_observation(float(MAX_VALID_READ_SECONDS)) == (True, None)


async def test_sufficient_history_produces_robust_observed_effort(async_db):
    """Median-based observed effort ignores noise and outliers."""
    user_id = await _ensure_user(async_db)
    thread = await _add_thread(async_db, user_id, "Sufficient History")
    issue_a = await _add_issue(async_db, thread, 1)
    base = datetime.now(UTC) - timedelta(hours=24)
    noise_minutes = 0.25
    outlier_minutes = MAX_VALID_READ_SECONDS / 60.0 + 60.0

    await _link_read(async_db, thread, minutes=8.0, rolled_at=base, issue=issue_a)
    await _link_read(
        async_db,
        thread,
        minutes=12.0,
        rolled_at=base + timedelta(hours=1),
        issue=issue_a,
    )
    await _link_read(
        async_db,
        thread,
        minutes=14.0,
        rolled_at=base + timedelta(hours=2),
        issue=issue_a,
    )
    # Instant-marking noise: a rating seconds after the roll.
    await _link_read(
        async_db,
        thread,
        minutes=noise_minutes,
        rolled_at=base + timedelta(hours=3),
        issue=issue_a,
    )
    # Extreme long-duration outlier: an abandoned tab, not effort.
    await _link_read(
        async_db,
        thread,
        minutes=outlier_minutes,
        rolled_at=base + timedelta(hours=4),
        issue=issue_a,
    )

    observations = await collect_classified_observations(async_db, user_id)
    assert len(observations) == 5
    exclusion_reasons = {
        classified.reason_code for classified in observations if not classified.valid
    }
    assert exclusion_reasons == {ExclusionReason.TOO_SHORT, ExclusionReason.TOO_LONG}

    _, by_thread = aggregate_observations(observations)
    assert by_thread[thread.id].sample_count == 3

    estimate = await compute_effort_estimate(
        async_db, user_id=user_id, thread_id=thread.id, issue_id=issue_a.id
    )
    assert estimate.source == EstimateSource.OBSERVED_ISSUE
    assert estimate.minutes == pytest.approx(12.0)
    assert estimate.band == "balanced"
    assert estimate.sample_count == 3


async def test_sparse_issue_history_falls_back_to_thread_history(async_db):
    """One issue observation is below the trust threshold; thread history wins."""
    user_id = await _ensure_user(async_db)
    thread = await _add_thread(async_db, user_id, "Sparse Issue")
    sparse_issue = await _add_issue(async_db, thread, 1)
    other_issue_a = await _add_issue(async_db, thread, 2)
    other_issue_b = await _add_issue(async_db, thread, 3)
    base = datetime.now(UTC) - timedelta(hours=12)

    await _link_read(
        async_db, thread, minutes=20.0, rolled_at=base, issue=sparse_issue
    )
    await _link_read(
        async_db,
        thread,
        minutes=10.0,
        rolled_at=base + timedelta(hours=1),
        issue=other_issue_a,
    )
    await _link_read(
        async_db,
        thread,
        minutes=8.0,
        rolled_at=base + timedelta(hours=2),
        issue=other_issue_b,
    )

    observations = await collect_classified_observations(async_db, user_id)
    by_issue, by_thread = aggregate_observations(observations)
    assert by_issue[(thread.id, sparse_issue.id)].sample_count < MIN_OBSERVED_SAMPLES
    assert by_thread[thread.id].sample_count >= MIN_OBSERVED_SAMPLES

    estimate = await compute_effort_estimate(
        async_db, user_id=user_id, thread_id=thread.id, issue_id=sparse_issue.id
    )
    assert estimate.source == EstimateSource.OBSERVED_THREAD
    assert estimate.minutes == pytest.approx(10.0)
    assert estimate.band == "light"


async def test_missing_observed_history_falls_back_to_publication_era(async_db):
    """A new comic with confirmed metadata uses the documented era prior."""
    user_id = await _ensure_user(async_db)
    thread = await _add_thread(async_db, user_id, "Brand New Comic")
    await _confirm_series_metadata(async_db, thread, "2021-06-01")

    estimate = await compute_effort_estimate(
        async_db, user_id=user_id, thread_id=thread.id, issue_id=None
    )
    assert estimate.source == EstimateSource.ERA_PRIOR
    assert estimate.minutes == pytest.approx(17.0)
    assert estimate.band == "balanced"
    assert estimate.confidence == pytest.approx(ERA_PRIOR_CONFIDENCE)
    assert estimate.sample_count == 0


async def test_no_history_and_no_metadata_yields_neutral_estimate(async_db):
    """Without observations or confirmed metadata nothing is invented."""
    user_id = await _ensure_user(async_db)
    thread = await _add_thread(async_db, user_id, "Unknown Comic")

    estimate = await compute_effort_estimate(
        async_db, user_id=user_id, thread_id=thread.id, issue_id=None
    )
    assert estimate.source == EstimateSource.UNKNOWN
    assert estimate.minutes is None
    assert estimate.band == "unknown"
    assert estimate.confidence == 0.0
    assert estimate.sample_count == 0


async def test_observed_history_takes_precedence_over_era_prior(async_db):
    """Observed history outranks a confirmed publication-era prior."""
    user_id = await _ensure_user(async_db)
    thread = await _add_thread(async_db, user_id, "Observed Beats Era")
    await _confirm_series_metadata(async_db, thread, "1995-03-01")
    base = datetime.now(UTC) - timedelta(hours=6)

    await _link_read(async_db, thread, minutes=6.0, rolled_at=base)
    await _link_read(async_db, thread, minutes=8.0, rolled_at=base + timedelta(hours=1))

    estimate = await compute_effort_estimate(
        async_db, user_id=user_id, thread_id=thread.id, issue_id=None
    )
    assert estimate.source == EstimateSource.OBSERVED_THREAD
    assert estimate.minutes == pytest.approx(7.0)


async def test_roll_records_decision_time_recommendation_context(auth_client, async_db):
    """A roll persists the versioned estimate/source that existed at decision time."""
    me_response = await auth_client.get("/api/auth/me")
    assert me_response.status_code == 200
    user_result = await async_db.execute(select(User).where(User.id == me_response.json()["id"]))
    user = user_result.scalar_one()

    thread = await _add_thread(async_db, user.id, "Era Candidate")
    await _confirm_series_metadata(async_db, thread, "2021-06-01")

    roll_response = await auth_client.post("/api/roll/")
    assert roll_response.status_code == 200
    body = roll_response.json()
    assert body["thread_id"] == thread.id

    roll_event_result = await async_db.execute(
        select(Event).where(Event.type == "roll").order_by(Event.id.desc()).limit(1)
    )
    roll_event = roll_event_result.scalar_one()
    context = roll_event.recommendation_context
    assert context is not None
    assert context["context_version"] == RECOMMENDATION_CONTEXT_VERSION
    candidate = context["selected_candidate"]
    assert candidate["thread_id"] == thread.id
    assert candidate["effort_source"] == EstimateSource.ERA_PRIOR.value
    assert candidate["effort_minutes"] == pytest.approx(17.0)
    assert candidate["effort_band"] == "balanced"
    assert candidate["effort_confidence"] == pytest.approx(ERA_PRIOR_CONFIDENCE)
    assert candidate["effort_sample_count"] == 0


async def test_override_roll_records_decision_time_recommendation_context(
    auth_client, async_db
):
    """Manual overrides also persist decision-time context without changing selection."""
    me_response = await auth_client.get("/api/auth/me")
    assert me_response.status_code == 200
    user_result = await async_db.execute(select(User).where(User.id == me_response.json()["id"]))
    user = user_result.scalar_one()

    thread = await _add_thread(async_db, user.id, "Override Candidate", queue_position=1)
    override_response = await auth_client.post(
        "/api/roll/override", json={"thread_id": thread.id}
    )
    assert override_response.status_code == 200

    override_event_result = await async_db.execute(
        select(Event)
        .where(Event.type == "roll")
        .where(Event.selection_method == "override")
        .order_by(Event.id.desc())
        .limit(1)
    )
    override_event = override_event_result.scalar_one()
    assert override_event.selected_thread_id == thread.id
    context = override_event.recommendation_context
    assert context is not None
    candidate = context["selected_candidate"]
    assert candidate["thread_id"] == thread.id
    assert candidate["effort_source"] == EstimateSource.UNKNOWN.value
    assert candidate["effort_minutes"] is None
    assert candidate["effort_band"] == "unknown"


async def test_legacy_random_roll_selection_behavior_unchanged(auth_client, async_db):
    """Random rolls keep their legacy contract while context recording is added."""
    me_response = await auth_client.get("/api/auth/me")
    assert me_response.status_code == 200
    user_result = await async_db.execute(select(User).where(User.id == me_response.json()["id"]))
    user = user_result.scalar_one()

    pool_ids = set()
    for index in range(1, 4):
        thread = await _add_thread(async_db, user.id, f"Pool {index}", queue_position=index)
        pool_ids.add(thread.id)
    await _add_thread(async_db, user.id, "Completed", queue_position=9, status="completed")
    await _add_thread(async_db, user.id, "Blocked", queue_position=10, is_blocked=True)

    legacy_fields = {
        "thread_id",
        "title",
        "format",
        "issues_remaining",
        "queue_position",
        "die_size",
        "result",
        "offset",
        "snoozed_count",
        "explanation",
        "issue_id",
        "issue_number",
        "next_issue_id",
        "next_issue_number",
        "total_issues",
        "reading_progress",
    }

    for _ in range(3):
        roll_response = await auth_client.post("/api/roll/")
        assert roll_response.status_code == 200
        body = roll_response.json()
        assert set(body) == legacy_fields
        assert body["die_size"] == 6
        assert body["thread_id"] in pool_ids
        assert 1 <= body["result"] <= len(pool_ids)
        assert body["offset"] == 0
        assert body["snoozed_count"] == 0

        event_result = await async_db.execute(
            select(Event)
            .where(Event.type == "roll")
            .where(Event.selection_method == "random")
            .order_by(Event.id.desc())
            .limit(1)
        )
        latest_random = event_result.scalar_one()
        assert latest_random.selected_thread_id == body["thread_id"]

        dismiss_response = await auth_client.post("/api/roll/dismiss-pending")
        assert dismiss_response.status_code == 204
