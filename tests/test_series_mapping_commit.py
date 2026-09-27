"""Contract tests for the series mapping commit endpoint.

The frozen preview contract from #2721 classifies at most one row per preview as
``safe_exact_match``: a bulk-safe row must carry a unique normalized issue number
equal to the anchor issue's number. These tests seed a local-catalog scope that
produces exactly that shape, plus one row for every other classification so the
commit response can be checked for truthful leftovers.

Seeded scope for a series with a confirmed thread mapping on threads 1 and 2:

- issue 6  (thread 2, "6")  confirmed mapping to a foreign provider
           -> needs_review_conflict, and it is the preview anchor issue
- issue 7  (thread 2, "7")  candidate comicvine mapping -> unresolved
- issue 8  (thread 2, "8")  confirmed comicvine mapping -> already_confirmed
- issue 9  (thread 2, "Annual 1") candidate comicvine mapping -> excluded_special
- issue 10 (thread 2, "1.5") candidate comicvine mapping -> needs_review_ambiguous
- issue 11 (thread 1, "6")  candidate comicvine mapping -> safe_exact_match

Only issue 11 is bulk-approvable, and only when the preview is anchored on
issue 6. Approving the cross-provider conflict row is impossible through the
frozen classification, so ``confirmed_mapping_conflict`` is exercised as the
concurrent-writer guard it is, with an injected scope snapshot.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.event import Event
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    SeriesMappingCommitReceipt,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.session import Session as SessionModel
from app.models.thread import Thread
from app.models.user import User
from app.services import catalog as catalog_service
from app.services.catalog import (
    _generate_preview_token,
    commit_series_mapping,
    preview_series_mapping,
)

SERIES_EXTERNAL_ID = "20764"
SERIES_IDENTITY_ID = 900
PROVIDER = "comicvine"

ORIGIN_ISSUE_ID = 6
ORIGIN_ISSUE_NUMBER = "6"
CONFLICT_EXTERNAL_ID = "cbl-9001"

SERIES_THREAD_IDS = (1, 2)

SAFE_EXTERNAL_ID = "400012346"

#: Seeded label -> (issue_number, provider, external_id, mapping_status).
SEED_ROWS: dict[str, tuple[str, str, str, str]] = {
    "7": ("7", PROVIDER, "400012347", "candidate"),
    "8": ("8", PROVIDER, "400012348", "confirmed"),
    "9": ("Annual 1", PROVIDER, "400012349", "candidate"),
    "10": ("1.5", PROVIDER, "400012350", "candidate"),
    "safe": (ORIGIN_ISSUE_NUMBER, PROVIDER, SAFE_EXTERNAL_ID, "candidate"),
}

SEED_EXPECTED_COUNTS = {
    "already_confirmed": 1,
    "safe_exact_match": 1,
    "needs_review_ambiguous": 1,
    "needs_review_conflict": 1,
    "unresolved": 1,
    "excluded_special": 1,
}

COMMIT_URL = "/api/v1/catalog/series-mappings/commit"
PREVIEW_URL = "/api/v1/catalog/series-mappings/preview"

CLASSIFICATION_DIGEST = (
    "already_confirmed:1|safe_exact_match:1|needs_review_ambiguous:1|"
    "needs_review_conflict:1|unresolved:1|excluded_special:1"
)


@dataclass(frozen=True)
class SeededScope:
    """Resolved identifiers for one seeded preview scope."""

    user_id: int
    thread_id: int
    origin_issue_id: int
    issue_ids: dict[str, int] = field(default_factory=dict)
    issue_numbers: list[str] = field(default_factory=list)


async def _seed_local_scope(
    session: AsyncSession,
    sample_data: dict[str, object],
) -> SeededScope:
    """Seed a local-catalog scope whose preview yields one safe_exact_match row.

    Args:
        session: Database session used for seeding.
        sample_data: The shared ``sample_data`` fixture payload.

    Returns:
        The resolved identifiers for the seeded scope.
    """
    threads: list[Thread] = sample_data["threads"]
    user: User = sample_data["user"]
    assert user.id is not None

    series_identity = ExternalIdentity(
        id=SERIES_IDENTITY_ID,
        provider=PROVIDER,
        entity_type="series",
        external_id=SERIES_EXTERNAL_ID,
        external_url="https://comicvine.gamespot.com/amazing-spider-man-1963/4050-20764/",
        metadata_json={"name": "Amazing Spider-Man (1963)", "publisher": {"name": "Marvel Comics"}},
    )
    session.add(series_identity)
    await session.flush()

    for thread_id in SERIES_THREAD_IDS:
        session.add(
            ThreadExternalSeriesMapping(
                thread_id=thread_id,
                external_identity_id=series_identity.id,
                status="confirmed",
                evidence_source="seed",
                confidence=1.0,
            )
        )

    # The anchor issue carries a confirmed cross-provider mapping, which is the
    # only way the frozen classification can surface a conflict row.
    origin_issue = await session.get(Issue, ORIGIN_ISSUE_ID)
    assert origin_issue is not None
    origin_issue.issue_number = ORIGIN_ISSUE_NUMBER
    conflict_identity = ExternalIdentity(
        provider="cbl",
        entity_type="issue",
        external_id=CONFLICT_EXTERNAL_ID,
        external_url="https://comicbookdb.com/issue/9001",
        metadata_json={"name": "Cross-provider seed"},
    )
    session.add(conflict_identity)
    await session.flush()
    session.add(
        IssueExternalIdentityMapping(
            issue_id=origin_issue.id,
            external_identity_id=conflict_identity.id,
            status="confirmed",
            evidence_source="seed_conflict",
            confidence=1.0,
        )
    )

    # The bulk-safe row lives in a second thread so the shared issue number stays
    # unique in each thread's uq_issue_thread_number constraint.
    safe_issue = Issue(
        thread_id=threads[0].id,
        issue_number=ORIGIN_ISSUE_NUMBER,
        position=1,
        status="unread",
        read_at=None,
        created_at=datetime.now(UTC),
    )
    session.add(safe_issue)
    await session.flush()

    issue_ids: dict[str, int] = {"safe": safe_issue.id, "conflict": origin_issue.id}
    issue_numbers: list[str] = [ORIGIN_ISSUE_NUMBER]

    for label, (issue_number, provider, external_id, mapping_status) in SEED_ROWS.items():
        issue_id = safe_issue.id if label == "safe" else int(label)
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        issue.issue_number = issue_number
        identity = ExternalIdentity(
            provider=provider,
            entity_type="issue",
            external_id=external_id,
            external_url=f"https://example.test/{provider}/{external_id}",
            metadata_json={"name": f"Seed {external_id}", "issue_number": issue_number},
        )
        session.add(identity)
        await session.flush()
        session.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status=mapping_status,
                evidence_source="seed",
                confidence=1.0 if mapping_status == "confirmed" else 0.5,
            )
        )
        issue_ids[label] = issue.id
        issue_numbers.append(issue_number)

    await session.commit()
    return SeededScope(
        user_id=user.id,
        thread_id=threads[1].id,
        origin_issue_id=origin_issue.id,
        issue_ids=issue_ids,
        issue_numbers=issue_numbers,
    )


async def _preview_scope(session: AsyncSession, scope: SeededScope) -> dict[str, object]:
    """Run the real preview service over the seeded scope.

    Args:
        session: Database session.
        scope: Seeded scope identifiers.

    Returns:
        The resolved preview scope payload.
    """
    return await preview_series_mapping(
        session,
        user_id=scope.user_id,
        origin_issue_id=scope.origin_issue_id,
        provider=PROVIDER,
        provider_series_external_id=SERIES_EXTERNAL_ID,
    )


async def _issue_token(session: AsyncSession, scope: SeededScope) -> str:
    """Return a signed preview token for the seeded scope.

    Args:
        session: Database session.
        scope: Seeded scope identifiers.

    Returns:
        The signed preview token string.
    """
    preview = await _preview_scope(session, scope)
    token = preview["preview_token"]
    assert isinstance(token, str)
    return token


async def _mapping_for(session: AsyncSession, issue_id: int) -> IssueExternalIdentityMapping:
    """Load the mapping row set for a seeded issue, ordered by id.

    Args:
        session: Database session.
        issue_id: ComicPile issue ID.

    Returns:
        Every mapping row for the issue.
    """
    rows = (
        await session.execute(
            select(IssueExternalIdentityMapping)
            .where(IssueExternalIdentityMapping.issue_id == issue_id)
            .order_by(IssueExternalIdentityMapping.id)
        )
    ).scalars().all()
    return list(rows)


async def _single_mapping_for(
    session: AsyncSession, issue_id: int
) -> IssueExternalIdentityMapping:
    """Load the single mapping row for a seeded issue.

    Args:
        session: Database session.
        issue_id: ComicPile issue ID.

    Returns:
        The one and only mapping row for the issue.
    """
    rows = await _mapping_for(session, issue_id)
    assert len(rows) == 1
    return rows[0]


async def _receipt_count(session: AsyncSession, user_id: int) -> int:
    """Count stored commit receipts for a user.

    Args:
        session: Database session.
        user_id: Owner user ID.

    Returns:
        Number of receipt rows for the user.
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(SeriesMappingCommitReceipt)
                .where(SeriesMappingCommitReceipt.user_id == user_id)
            )
        ).scalar_one()
    )


def _scope_snapshot(*, anchor_status: str, anchor_external_id: str = SAFE_EXTERNAL_ID):
    """Build a scope resolver that reports a fixed anchor row.

    Used to model a concurrent writer that changes the anchor between the
    commit-time scope recomputation and the confirmed-mapping guard.

    Args:
        anchor_status: Status reported for the anchor row.
        anchor_external_id: Provider external ID reported for the anchor row.

    Returns:
        An async callable matching the service's scope resolver signature.
    """

    async def _resolve(
        db: AsyncSession,
        *,
        user_id: int,
        origin_issue_id: int,
        provider: str,
        provider_series_external_id: str,
    ) -> dict[str, object]:
        del db, user_id, origin_issue_id, provider, provider_series_external_id
        rows: list[dict[str, object]] = []
        for label, (issue_number, row_provider, external_id, status) in SEED_ROWS.items():
            is_anchor = label == "safe"
            rows.append(
                {
                    "issue_id": 0,
                    "comicpile_issue_id": 0,
                    "issue_number": issue_number,
                    "current_mapping_status": anchor_status if is_anchor else status,
                    "provider": row_provider,
                    "external_id": anchor_external_id if is_anchor else external_id,
                    "classification": "safe_exact_match" if is_anchor else "unresolved",
                }
            )
        return {
            "scope": {
                "status": "available",
                "scope_key": f"exact:{ORIGIN_ISSUE_ID}:{ORIGIN_ISSUE_NUMBER}",
                "origin_issue_id": ORIGIN_ISSUE_ID,
                "series_label": "Amazing Spider-Man (1963)",
                "basis": "exact_match_found",
            },
            "provider_series": {"id": SERIES_EXTERNAL_ID},
            "counts": dict(SEED_EXPECTED_COUNTS),
            "rows": rows,
            "issued_at": 0.0,
            "expires_at": 0.0,
            "issue_numbers": [ORIGIN_ISSUE_NUMBER, "7", "8", "Annual 1", "1.5"],
            "classification_digest": CLASSIFICATION_DIGEST,
        }

    return _resolve


def _aligned_scope_snapshot(scope: SeededScope):
    """Build a scope resolver whose rows match the real preview for a seeded scope.

    Used to prove the commit-time ownership gate independently of the row query,
    which already restricts rows to the caller's own threads.

    Args:
        scope: Seeded scope identifiers.

    Returns:
        An async callable matching the service's scope resolver signature.
    """
    inner = _scope_snapshot(anchor_status="candidate")

    async def _resolve(
        db: AsyncSession,
        *,
        user_id: int,
        origin_issue_id: int,
        provider: str,
        provider_series_external_id: str,
    ) -> dict[str, object]:
        payload = await inner(
            db,
            user_id=user_id,
            origin_issue_id=origin_issue_id,
            provider=provider,
            provider_series_external_id=provider_series_external_id,
        )
        rows = list(payload["rows"])
        for row in rows:
            issue_number = row["issue_number"]
            label = next(
                key for key, spec in SEED_ROWS.items() if spec[0] == issue_number
            )
            row["comicpile_issue_id"] = scope.issue_ids[label]
            row["issue_id"] = scope.issue_ids[label]
        rows.append(
            {
                "issue_id": scope.origin_issue_id,
                "comicpile_issue_id": scope.origin_issue_id,
                "issue_number": ORIGIN_ISSUE_NUMBER,
                "current_mapping_status": "confirmed",
                "provider": "cbl",
                "external_id": CONFLICT_EXTERNAL_ID,
                "classification": "needs_review_conflict",
            }
        )
        payload["rows"] = rows
        return payload

    return _resolve


async def _commit(
    auth_client: AsyncClient,
    *,
    token: str,
    idempotency_key: str,
    approved_row_ids: list[str],
) -> AsyncClient:
    """Issue a commit request.

    Args:
        auth_client: HTTP client to use.
        token: Signed preview token.
        idempotency_key: Idempotency key for the material request.
        approved_row_ids: Approved preview row identifiers.

    Returns:
        The awaited HTTP response.
    """
    return await auth_client.post(
        COMMIT_URL,
        json={
            "preview_token": token,
            "idempotency_key": idempotency_key,
            "approved_row_ids": approved_row_ids,
        },
    )


@pytest.fixture(autouse=True)
def _no_hydration_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep hydration out of the request path unless a test opts in.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(
        catalog_service,
        "schedule_series_mapping_hydration",
        lambda *, issue_ids: list(issue_ids),
    )


@pytest.mark.asyncio
async def test_commit_endpoint_is_the_frozen_path() -> None:
    """The commit route must be the slash-path URL the contract freezes."""
    from app.api import catalog

    commit_routes = [route for route in catalog.router.routes if route.path == COMMIT_URL]
    assert len(commit_routes) == 1
    assert "POST" in commit_routes[0].methods

    all_paths = {route.path for route in catalog.router.routes}
    assert not any(":commit" in path for path in all_paths)


@pytest.mark.asyncio
async def test_seeded_preview_classification_is_the_expected_shape(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """The seeded scope must reproduce the frozen classification contract."""
    scope = await _seed_local_scope(async_db, sample_data)

    response = await auth_client.post(
        PREVIEW_URL,
        json={
            "origin_issue_id": scope.origin_issue_id,
            "provider": PROVIDER,
            "provider_series_external_id": SERIES_EXTERNAL_ID,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"]["status"] == "available"
    assert payload["scope"]["scope_key"] == f"exact:{ORIGIN_ISSUE_ID}:{ORIGIN_ISSUE_NUMBER}"
    assert payload["counts"] == SEED_EXPECTED_COUNTS
    safe_rows = [row for row in payload["rows"] if row["classification"] == "safe_exact_match"]
    assert [row["issue_id"] for row in safe_rows] == [scope.issue_ids["safe"]]
    assert all(row["default_selected"] for row in safe_rows)
    assert all(row["default_selected"] is False for row in payload["rows"] if row not in safe_rows)


@pytest.mark.asyncio
async def test_commit_confirms_safe_rows_with_provenance_and_preserves_personal_state(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A bulk-safe approval confirms immediately and preserves all read state."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    read_issue: Issue = sample_data["issues"][0]
    thread: Thread = sample_data["threads"][1]
    session_row: SessionModel = sample_data["sessions"][0]
    before_read_at = read_issue.read_at
    before_status = read_issue.status
    before_next_unread = thread.next_unread_issue_id
    before_session_start = session_row.start_die

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-success-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert response.status_code == 200
    assert response.json() == {
        "idempotency_key": "key-success-1",
        "confirmed_issue_ids": [safe_id],
        "already_confirmed_issue_ids": [scope.issue_ids["8"]],
        "needs_review_issue_ids": [
            scope.origin_issue_id,
            scope.issue_ids["7"],
            scope.issue_ids["10"],
        ],
        "hydration_queued_issue_ids": [safe_id],
        "series_mapping": {
            "provider": PROVIDER,
            "external_id": SERIES_EXTERNAL_ID,
            "status": "confirmed",
            "evidence_source": "user_series_confirmation",
        },
    }

    mapping = await _single_mapping_for(async_db, safe_id)
    assert mapping.status == "confirmed"
    assert mapping.evidence_source == "user_series_confirmation"
    assert mapping.confidence == 1.0

    identity = await async_db.get(ExternalIdentity, mapping.external_identity_id)
    assert identity is not None
    assert (identity.provider, identity.external_id, identity.entity_type) == (
        PROVIDER,
        SAFE_EXTERNAL_ID,
        "issue",
    )

    await async_db.refresh(read_issue)
    await async_db.refresh(thread)
    await async_db.refresh(session_row)
    assert read_issue.read_at == before_read_at
    assert read_issue.status == before_status
    assert thread.next_unread_issue_id == before_next_unread
    assert session_row.start_die == before_session_start

    event_count = (
        await async_db.execute(
            select(func.count()).select_from(Event).where(Event.thread_id == thread.id)
        )
    ).scalar_one()
    assert int(event_count) == 0
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_commit_leaves_already_confirmed_and_leftover_rows_untouched(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Only the approved safe row is written; every other row keeps its state."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    before: dict[int, list[tuple[int, str, str | None, float | None]]] = {}
    for issue_id in [scope.origin_issue_id, *(scope.issue_ids[label] for label in SEED_ROWS)]:
        before[issue_id] = [
            (row.id, row.status, row.evidence_source, row.confidence)
            for row in await _mapping_for(async_db, issue_id)
        ]

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-leftovers-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 200
    for issue_id, expected in before.items():
        if issue_id == scope.issue_ids["safe"]:
            continue
        actual = [
            (row.id, row.status, row.evidence_source, row.confidence)
            for row in await _mapping_for(async_db, issue_id)
        ]
        assert actual == expected


@pytest.mark.asyncio
async def test_commit_with_no_approved_rows_confirms_nothing(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """An empty approval list is legal and truthfully reports the leftovers."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-empty-approval-1",
        approved_row_ids=[],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_issue_ids"] == []
    assert body["hydration_queued_issue_ids"] == []
    assert body["already_confirmed_issue_ids"] == [scope.issue_ids["8"]]
    assert body["needs_review_issue_ids"] == [
        scope.origin_issue_id,
        scope.issue_ids["7"],
        scope.issue_ids["10"],
    ]
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"


@pytest.mark.asyncio
async def test_identical_retry_is_idempotent(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """An identical retry replays the stored result and writes nothing new."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    first = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-retry-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )
    assert first.status_code == 200
    mapping_after_first = await _single_mapping_for(async_db, safe_id)

    second = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-retry-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert second.status_code == 200
    assert second.json() == first.json()

    mapping_after_retry = await _single_mapping_for(async_db, safe_id)
    assert mapping_after_retry.id == mapping_after_first.id
    assert mapping_after_retry.status == "confirmed"
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_identical_retry_with_reordered_rows_is_idempotent(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Row order is not material input, so a reordered retry still replays."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    first = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-retry-order-1",
        approved_row_ids=[f"issue:{safe_id}", f"issue:{safe_id}"],
    )
    assert first.status_code == 200

    second = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-retry-order-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert second.status_code == 200
    assert second.json() == first.json()
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_rows_is_a_conflict(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Reusing a key with materially different approved rows is a 409."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    first = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-rows-1",
        approved_row_ids=[],
    )
    assert first.status_code == 200

    second = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-rows-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "idempotency_conflict"
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_reused_key_with_different_token_is_a_conflict(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Reusing a key with a different referenced preview is a 409."""
    scope = await _seed_local_scope(async_db, sample_data)
    first_token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    preview = await _preview_scope(async_db, scope)
    issued_at = float(preview["issued_at"])
    other_token = _generate_preview_token(
        user_id=scope.user_id,
        provider=PROVIDER,
        provider_series_external_id="20764",
        origin_issue_id=scope.origin_issue_id,
        scope_key=f"exact:{ORIGIN_ISSUE_ID}:{ORIGIN_ISSUE_NUMBER}",
        issued_at=issued_at,
        expires_at=issued_at + 600,
        issue_numbers=list(preview["issue_numbers"]),
        classification_digest="already_confirmed:0|safe_exact_match:1",
    )

    first = await _commit(
        auth_client,
        token=first_token,
        idempotency_key="key-token-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )
    assert first.status_code == 200

    second = await _commit(
        auth_client,
        token=other_token,
        idempotency_key="key-token-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "idempotency_conflict"
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_expired_token_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A token older than the ten-minute TTL is a 409 preview_expired."""
    scope = await _seed_local_scope(async_db, sample_data)
    preview = await _preview_scope(async_db, scope)
    issued_at = float(preview["issued_at"])

    stale = _generate_preview_token(
        user_id=scope.user_id,
        provider=PROVIDER,
        provider_series_external_id=SERIES_EXTERNAL_ID,
        origin_issue_id=scope.origin_issue_id,
        scope_key=f"exact:{ORIGIN_ISSUE_ID}:{ORIGIN_ISSUE_NUMBER}",
        issued_at=issued_at - 1200,
        expires_at=issued_at - 600,
        issue_numbers=list(preview["issue_numbers"]),
        classification_digest=str(preview["classification_digest"]),
    )

    response = await _commit(
        auth_client,
        token=stale,
        idempotency_key="key-expired-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "preview_expired"
    assert await _receipt_count(async_db, scope.user_id) == 0
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"


@pytest.mark.asyncio
async def test_tampered_token_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A token whose payload was edited no longer verifies."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    decoded = json.loads(token)
    decoded["payload"]["provider_series_external_id"] = "99999"
    tampered = json.dumps(decoded)

    response = await _commit(
        auth_client,
        token=tampered,
        idempotency_key="key-tampered-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "preview_stale"
    assert await _receipt_count(async_db, scope.user_id) == 0
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"


@pytest.mark.asyncio
async def test_another_users_token_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A token bound to a different user is never accepted."""
    from app.auth import create_access_token

    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    foreign = User(id=2, username="series-mapping-outsider", created_at=datetime.now(UTC))
    async_db.add(foreign)
    await async_db.commit()
    auth_client.headers["Authorization"] = (
        f"Bearer {create_access_token(data={'sub': foreign.username, 'jti': 'foreign'})}"
    )

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-foreign-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "preview_stale"
    assert await _receipt_count(async_db, scope.user_id) == 0


@pytest.mark.asyncio
async def test_changed_mapping_state_is_preview_stale(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A bound mapping fact changing after preview rejects the commit."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    leftover = await _single_mapping_for(async_db, scope.issue_ids["7"])
    leftover.status = "confirmed"
    await async_db.commit()

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-stale-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "preview_stale"
    assert await _receipt_count(async_db, scope.user_id) == 0
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"


@pytest.mark.asyncio
async def test_changed_issue_number_is_preview_stale(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A bound issue-number fact changing after preview rejects the commit."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    moved = await _single_mapping_for(async_db, scope.issue_ids["7"])
    moved.status = "unresolved"
    await async_db.commit()
    issue = await async_db.get(Issue, scope.issue_ids["7"])
    assert issue is not None
    issue.issue_number = "77"
    await async_db.commit()

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-stale-number-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "preview_stale"
    assert await _receipt_count(async_db, scope.user_id) == 0
    assert (await _single_mapping_for(async_db, scope.issue_ids["safe"])).status == "candidate"


@pytest.mark.asyncio
async def test_removed_provider_identity_is_preview_stale(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """A selected provider identity disappearing after preview is stale."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    series = await async_db.get(ExternalIdentity, SERIES_IDENTITY_ID)
    assert series is not None
    await async_db.delete(series)
    await async_db.commit()

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-stale-provider-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code in {409, 503}
    assert await _receipt_count(async_db, scope.user_id) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unresolved", "already_confirmed", "special", "ambiguous", "conflict", "absent", "non_numeric", "zero", "bad_prefix", "mixed"])
async def test_non_safe_approved_rows_are_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    case: str,
) -> None:
    """Only safe_exact_match rows from the referenced preview may be approved."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    row_by_case = {
        "unresolved": f"issue:{scope.issue_ids['7']}",
        "already_confirmed": f"issue:{scope.issue_ids['8']}",
        "special": f"issue:{scope.issue_ids['9']}",
        "ambiguous": f"issue:{scope.issue_ids['10']}",
        "conflict": f"issue:{scope.origin_issue_id}",
        "absent": "issue:999999",
        "non_numeric": "issue:abc",
        "zero": "issue:0",
        "bad_prefix": "volume:6",
        "mixed": f"issue:{safe_id},issue:{scope.issue_ids['7']}",
    }
    approved_row_ids = row_by_case[case].split(",")

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key=f"key-invalid-{case}",
        approved_row_ids=approved_row_ids,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_approved_row"
    assert await _receipt_count(async_db, scope.user_id) == 0

    expected_status = {
        scope.origin_issue_id: "confirmed",
        scope.issue_ids["7"]: "candidate",
        scope.issue_ids["8"]: "confirmed",
        scope.issue_ids["9"]: "candidate",
        scope.issue_ids["10"]: "candidate",
        safe_id: "candidate",
    }
    for issue_id, expected in expected_status.items():
        assert (await _single_mapping_for(async_db, issue_id)).status == expected


@pytest.mark.asyncio
async def test_approving_another_users_issue_is_rejected(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Ownership is re-checked at commit time, not trusted from the token."""
    from app.auth import create_access_token

    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    foreign_thread = Thread(
        title="Outsider",
        format="Comic",
        issues_remaining=1,
        queue_position=9,
        status="active",
        user_id=2,
        created_at=datetime.now(UTC),
    )
    foreign_user = User(id=2, username="outsider-thread-owner", created_at=datetime.now(UTC))
    async_db.add_all([foreign_user, foreign_thread])
    await async_db.flush()
    foreign_issue = Issue(
        thread_id=foreign_thread.id,
        issue_number="1",
        position=1,
        status="unread",
        read_at=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(foreign_issue)
    await async_db.commit()

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(
            catalog_service,
            "resolve_series_mapping_scope",
            _aligned_scope_snapshot(scope),
        )
        auth_client.headers["Authorization"] = (
            f"Bearer {create_access_token(data={'sub': foreign_user.username, 'jti': 'foreign-thread'})}"
        )
        response = await _commit(
            auth_client,
            token=token,
            idempotency_key="key-foreign-issue-1",
            approved_row_ids=[f"issue:{foreign_issue.id}"],
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_approved_row"


@pytest.mark.asyncio
async def test_confirmed_conflict_from_a_concurrent_writer_is_a_409(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirmed same-provider identity committed by a racing writer wins.

    The frozen classification cannot produce a bulk-safe row for an issue that
    already holds a confirmed identity, so the race is injected between the
    commit-time scope recomputation and the confirmed-mapping guard.
    """
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    safe_mapping = await _single_mapping_for(async_db, safe_id)
    original_identity_id = safe_mapping.external_identity_id
    racer_identity = ExternalIdentity(
        provider=PROVIDER,
        entity_type="issue",
        external_id="400019999",
        external_url="https://example.test/comicvine/400019999",
        metadata_json={"name": "Racing writer identity"},
    )
    async_db.add(racer_identity)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=safe_id,
            external_identity_id=racer_identity.id,
            status="confirmed",
            evidence_source="racing_writer",
            confidence=1.0,
        )
    )
    await async_db.commit()

    monkeypatch.setattr(
        catalog_service,
        "resolve_series_mapping_scope",
        _scope_snapshot(anchor_status="candidate"),
    )

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-conflict-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "confirmed_mapping_conflict"
    assert await _receipt_count(async_db, scope.user_id) == 0

    rows = await _mapping_for(async_db, safe_id)
    confirmed = [row for row in rows if row.status == "confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0].evidence_source == "racing_writer"
    assert confirmed[0].external_identity_id == racer_identity.id
    candidate = next(row for row in rows if row.external_identity_id == original_identity_id)
    assert candidate.status == "candidate"


@pytest.mark.asyncio
async def test_identity_writes_are_transactional(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure part-way through the write phase leaves no partial state."""
    from app.repositories import catalog_repository

    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    async def _explode(**kwargs: object) -> bool:
        del kwargs
        raise RuntimeError("simulated mapping write failure")

    monkeypatch.setattr(catalog_repository, "confirm_issue_mapping", _explode)

    with pytest.raises(RuntimeError):
        await _commit(
            auth_client,
            token=token,
            idempotency_key="key-rollback-1",
            approved_row_ids=[f"issue:{safe_id}"],
        )

    mapping = await _single_mapping_for(async_db, safe_id)
    assert mapping.status == "candidate"
    assert mapping.evidence_source == "seed"
    assert mapping.confidence == 0.5
    assert await _receipt_count(async_db, scope.user_id) == 0


@pytest.mark.asyncio
async def test_hydration_is_dispatched_after_the_identity_commit(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hydration is queued for newly confirmed rows only, and runs post-commit."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    observed: list[tuple[int, str | None, str | None]] = []

    async def _record_hydration(issue_id: int) -> None:
        rows = await _mapping_for(async_db, issue_id)
        observed.append((issue_id, rows[0].status, rows[0].evidence_source))

    monkeypatch.setattr(catalog_service, "_get_comicvine_client", lambda: object())
    monkeypatch.setattr(catalog_service, "_run_series_mapping_hydration", _record_hydration)

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-hydration-1",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert response.status_code == 200
    assert response.json()["hydration_queued_issue_ids"] == [safe_id]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert observed == [(safe_id, "confirmed", "user_series_confirmation")]


@pytest.mark.asyncio
async def test_hydration_is_not_queued_for_already_confirmed_rows(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty approval list queues no hydration work at all."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    observed: list[int] = []

    async def _record_hydration(issue_id: int) -> None:
        observed.append(issue_id)

    monkeypatch.setattr(catalog_service, "_get_comicvine_client", lambda: object())
    monkeypatch.setattr(catalog_service, "_run_series_mapping_hydration", _record_hydration)

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-hydration-empty-1",
        approved_row_ids=[],
    )

    assert response.status_code == 200
    assert response.json()["hydration_queued_issue_ids"] == []
    await asyncio.sleep(0)
    assert observed == []


@pytest.mark.asyncio
async def test_hydration_failure_does_not_roll_back_confirmed_identity(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider failure during hydration leaves the confirmed mapping intact."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    attempted: list[int] = []

    async def _failing_hydration(issue_id: int) -> None:
        attempted.append(issue_id)
        raise RuntimeError("simulated provider outage")

    monkeypatch.setattr(catalog_service, "_get_comicvine_client", lambda: object())
    monkeypatch.setattr(catalog_service, "_run_series_mapping_hydration", _failing_hydration)

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-hydration-2",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert response.status_code == 200
    assert response.json()["confirmed_issue_ids"] == [safe_id]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert attempted == [safe_id]

    mapping = await _single_mapping_for(async_db, safe_id)
    assert mapping.status == "confirmed"
    assert mapping.evidence_source == "user_series_confirmation"
    assert await _receipt_count(async_db, scope.user_id) == 1


@pytest.mark.asyncio
async def test_hydration_is_not_queued_without_a_provider_client(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a provider client the response truthfully reports no hydration."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    monkeypatch.setattr(catalog_service, "_get_comicvine_client", lambda: None)

    response = await _commit(
        auth_client,
        token=token,
        idempotency_key="key-hydration-3",
        approved_row_ids=[f"issue:{safe_id}"],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_issue_ids"] == [safe_id]
    assert body["hydration_queued_issue_ids"] == []


@pytest.mark.asyncio
async def test_concurrent_identical_commits_converge(
    db_engine: Engine,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """Two truly concurrent identical commits produce one mapping and one receipt."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)
    safe_id = scope.issue_ids["safe"]

    # A committed, connection-independent seed is required so the two racing
    # transactions can actually see the scope they both revalidate.
    await db_engine.dispose()
    seeded_session_factory = async_sessionmaker(
        bind=db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with seeded_session_factory() as seed_session:
        await _seed_local_scope(seed_session, sample_data)
        token = await _issue_token(seed_session, scope)
        await seed_session.commit()

    async def _attempt() -> dict[str, object]:
        async with seeded_session_factory() as session:
            return await commit_series_mapping(
                session,
                user_id=scope.user_id,
                preview_token=token,
                idempotency_key="key-concurrent-1",
                approved_row_ids=[f"issue:{safe_id}"],
            )

    results = await asyncio.gather(_attempt(), _attempt())

    assert results[0] == results[1]
    assert results[0]["confirmed_issue_ids"] == [safe_id]

    async with seeded_session_factory() as verify_session:
        assert await _receipt_count(verify_session, scope.user_id) == 1
        confirmed = (
            await verify_session.execute(
                select(IssueExternalIdentityMapping).where(
                    IssueExternalIdentityMapping.issue_id == safe_id,
                    IssueExternalIdentityMapping.status == "confirmed",
                )
            )
        ).scalars().all()
        assert len(confirmed) == 1
        assert confirmed[0].evidence_source == "user_series_confirmation"


@pytest.mark.asyncio
async def test_commit_requires_authentication(
    client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict[str, object],
) -> None:
    """An unauthenticated commit is refused before any state is read."""
    scope = await _seed_local_scope(async_db, sample_data)
    token = await _issue_token(async_db, scope)

    response = await _commit(
        client,
        token=token,
        idempotency_key="key-anon-1",
        approved_row_ids=[f"issue:{scope.issue_ids['safe']}"],
    )

    assert response.status_code == 401
    assert await _receipt_count(async_db, scope.user_id) == 0


@pytest.mark.asyncio
async def test_missing_request_fields_are_rejected(
    auth_client: AsyncClient,
) -> None:
    """The request schema requires token, key, and approved rows."""
    response = await auth_client.post(
        COMMIT_URL,
        json={"idempotency_key": "key-missing-1", "approved_row_ids": []},
    )
    assert response.status_code == 422
