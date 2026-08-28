"""Tests for Taste Bank verdict API endpoints (issue #1749)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token
from app.models import TasteSignal, User
from app.schemas.taste import SignalType, TasteSignal as EligibilitySignal, Verdict
from app.services.prompt_eligibility import evaluate_prompt_eligibility

VERDICT_URL = "/api/v1/users/me/taste-signals/creator/creator:writer:dk/verdict"
LIST_URL = "/api/v1/users/me/taste-signals"


async def _seed_signal(
    async_db: AsyncSession,
    user_id: int,
    signal_type: str = "creator",
    external_key: str = "creator:writer:dk",
    **overrides: object,
) -> TasteSignal:
    """Insert one taste-signal row directly and return it refreshed.

    Args:
        async_db: Async database session for direct database writes.
        user_id: Owning user id for the seeded row.
        signal_type: Category of the seeded signal.
        external_key: Stable normalized key of the seeded signal.
        overrides: Optional column overrides applied to the row.

    Returns:
        The persisted and refreshed ``TasteSignal`` instance.
    """
    columns: dict[str, object] = {
        "user_id": user_id,
        "signal_type": signal_type,
        "external_key": external_key,
        "display_name": "Dk Writer",
        "affinity_estimate": None,
        "confidence": None,
        "evidence_count": 0,
        "distinct_thread_count": 0,
    }
    columns.update(overrides)
    signal = TasteSignal(**columns)
    async_db.add(signal)
    await async_db.commit()
    await async_db.refresh(signal)
    return signal


def _eligibility_input(signal: TasteSignal) -> EligibilitySignal:
    """Map a persisted signal onto the prompt-eligibility input schema.

    Args:
        signal: Persisted ``TasteSignal`` ORM instance.

    Returns:
        The equivalent eligibility-engine input with strong inferred stats.
    """
    return EligibilitySignal(
        user_id=signal.user_id,
        signal_type=SignalType(signal.signal_type),
        stable_key=signal.external_key,
        display_name=signal.display_name,
        affinity=0.8,
        confidence=0.9,
        evidence_count=5,
        evidence_diversity=3,
        verdict=(
            Verdict(signal.user_verdict) if signal.user_verdict is not None else None
        ),
    )


@pytest.mark.asyncio
async def test_put_verdict_creates_signal_and_returns_canonical_response(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A verdict on an unknown key creates the row and returns canonical data.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
    """
    response = await auth_client.put(VERDICT_URL, json={"verdict": "confirmed"})
    assert response.status_code == 200

    data = response.json()
    assert data["signal_type"] == "creator"
    assert data["external_key"] == "creator:writer:dk"
    assert data["user_verdict"] == "confirmed"
    assert data["user_id"] == 1
    assert datetime.fromisoformat(data["verdict_at"]) is not None
    assert data["affinity_estimate"] is None
    assert data["evidence_count"] == 0

    result = await async_db.execute(
        select(TasteSignal).where(
            TasteSignal.user_id == 1,
            TasteSignal.signal_type == "creator",
            TasteSignal.external_key == "creator:writer:dk",
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.parametrize("verdict", ["confirmed", "sometimes", "rejected"])
@pytest.mark.asyncio
async def test_each_verdict_updates_only_targeted_signal(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    verdict: str,
) -> None:
    """Each accepted verdict writes exactly its targeted signal row.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
        verdict: The verdict under test.
    """
    other = await _seed_signal(
        async_db, default_user.id, signal_type="team", external_key="team:xmen"
    )

    response = await auth_client.put(VERDICT_URL, json={"verdict": verdict})
    assert response.status_code == 200
    assert response.json()["user_verdict"] == verdict

    await async_db.refresh(other)
    result = await async_db.execute(
        select(TasteSignal).where(TasteSignal.user_id == default_user.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    untouched = next(row for row in rows if row.id == other.id)
    assert untouched.user_verdict is None


@pytest.mark.asyncio
async def test_repeated_same_verdict_is_idempotent(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Repeating a verdict never duplicates rows or corrupts state.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
    """
    first = await auth_client.put(VERDICT_URL, json={"verdict": "confirmed"})
    second = await auth_client.put(VERDICT_URL, json={"verdict": "confirmed"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["user_verdict"] == "confirmed"

    result = await async_db.execute(
        select(TasteSignal).where(TasteSignal.user_id == default_user.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].user_verdict == "confirmed"


@pytest.mark.asyncio
async def test_changed_verdict_overwrites_previous_value(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A later verdict replaces the stored one and advances the timestamp.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
    """
    await auth_client.put(VERDICT_URL, json={"verdict": "confirmed"})
    response = await auth_client.put(VERDICT_URL, json={"verdict": "sometimes"})
    assert response.status_code == 200
    assert response.json()["user_verdict"] == "sometimes"

    result = await async_db.execute(
        select(TasteSignal).where(TasteSignal.user_id == default_user.id)
    )
    row = result.scalar_one()
    assert row.user_verdict == "sometimes"
    assert row.verdict_at is not None


@pytest.mark.asyncio
async def test_verdict_write_preserves_inferred_columns_across_refresh(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Verdict writes never modify inferred columns, and refreshes keep them.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
    """
    seeded = await _seed_signal(
        async_db,
        default_user.id,
        affinity_estimate=-0.6,
        confidence=0.7,
        evidence_count=9,
        distinct_thread_count=4,
        first_observed_at=datetime.now(UTC),
        last_observed_at=datetime.now(UTC),
    )

    response = await auth_client.put(VERDICT_URL, json={"verdict": "rejected"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_verdict"] == "rejected"
    assert body["affinity_estimate"] == -0.6
    assert body["confidence"] == pytest.approx(0.7)
    assert body["evidence_count"] == 9
    assert body["distinct_thread_count"] == 4

    # Simulate a later inference refresh recomputing only derived columns;
    # the explicit verdict must survive it untouched.
    seeded.affinity_estimate = 0.4
    seeded.confidence = 0.95
    seeded.evidence_count = 12
    seeded.distinct_thread_count = 6
    await async_db.commit()

    listing = await auth_client.get(LIST_URL)
    assert listing.status_code == 200
    signals = {item["external_key"]: item for item in listing.json()["signals"]}
    refreshed = signals["creator:writer:dk"]
    assert refreshed["user_verdict"] == "rejected"
    assert refreshed["verdict_at"] is not None
    assert refreshed["affinity_estimate"] == 0.4


@pytest.mark.asyncio
async def test_rejected_signal_is_suppressed_from_discovery_prompts(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A signal rejected through the API is ineligible for normal prompts.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
    """
    reject_response = await auth_client.put(VERDICT_URL, json={"verdict": "rejected"})
    assert reject_response.status_code == 200

    result = await async_db.execute(
        select(TasteSignal).where(TasteSignal.user_id == default_user.id)
    )
    persisted = result.scalar_one()
    outcome = evaluate_prompt_eligibility([_eligibility_input(persisted)])

    assert outcome.candidates == []
    suppressed_keys = [entry.stable_key for entry in outcome.suppressed]
    assert persisted.external_key in suppressed_keys


@pytest.mark.asyncio
async def test_confirmed_signal_stays_prompt_eligible(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Confirming a strong signal keeps it eligible for discovery prompts.

    Args:
        auth_client: Authenticated HTTP client for API requests.
        async_db: Async database session for direct database queries.
        default_user: The authenticated test user.
    """
    confirm = await auth_client.put(VERDICT_URL, json={"verdict": "confirmed"})
    assert confirm.status_code == 200

    result = await async_db.execute(
        select(TasteSignal).where(TasteSignal.user_id == default_user.id)
    )
    persisted = result.scalar_one()
    outcome = evaluate_prompt_eligibility([_eligibility_input(persisted)])
    candidate_keys = [entry.signal.stable_key for entry in outcome.candidates]
    assert persisted.external_key in candidate_keys


@pytest.mark.asyncio
async def test_taste_signals_scoped_to_authenticated_user(
    client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """One user's verdicts never read or write another user's signals.

    Args:
        client: Unauthenticated HTTP client.
        async_db: Async database session for direct database queries.
    """
    now = datetime.now(UTC)
    user_a = User(username="taste_user_a", created_at=now)
    user_b = User(username="taste_user_b", created_at=now)
    async_db.add_all([user_a, user_b])
    await async_db.commit()
    await async_db.refresh(user_a)
    await async_db.refresh(user_b)

    token_a = create_access_token(data={"sub": user_a.username, "jti": "ta-1"})
    token_b = create_access_token(data={"sub": user_b.username, "jti": "tb-1"})
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    seeded = await _seed_signal(async_db, user_a.id)

    put_b = await client.put(
        VERDICT_URL, json={"verdict": "rejected"}, headers=headers_b
    )
    assert put_b.status_code == 200
    assert put_b.json()["user_id"] == user_b.id

    await async_db.refresh(seeded)
    assert seeded.user_verdict is None

    list_a = await client.get(LIST_URL, headers=headers_a)
    assert list_a.status_code == 200
    items_a = list_a.json()["signals"]
    assert len(items_a) == 1
    assert items_a[0]["user_id"] == user_a.id
    assert items_a[0]["user_verdict"] is None

    list_b = await client.get(LIST_URL, headers=headers_b)
    assert list_b.status_code == 200
    items_b = list_b.json()["signals"]
    assert len(items_b) == 1
    assert items_b[0]["user_id"] == user_b.id
    assert items_b[0]["user_verdict"] == "rejected"


@pytest.mark.asyncio
async def test_unauthenticated_taste_signal_requests_are_rejected(
    client: AsyncClient,
) -> None:
    """Both endpoints require authentication.

    Args:
        client: Unauthenticated HTTP client.
    """
    get_response = await client.get(LIST_URL)
    assert get_response.status_code in (401, 403)

    put_response = await client.put(VERDICT_URL, json={"verdict": "confirmed"})
    assert put_response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_invalid_verdict_returns_422(auth_client: AsyncClient) -> None:
    """An unsupported verdict literal fails request validation.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.put(VERDICT_URL, json={"verdict": "love-it"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unknown_signal_type_returns_422(auth_client: AsyncClient) -> None:
    """An unsupported signal type fails path validation.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.put(
        "/api/v1/users/me/taste-signals/color/red/verdict",
        json={"verdict": "confirmed"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_verdict_field_returns_422(auth_client: AsyncClient) -> None:
    """A request without a verdict fails request validation.

    Args:
        auth_client: Authenticated HTTP client for API requests.
    """
    response = await auth_client.put(VERDICT_URL, json={})
    assert response.status_code == 422
