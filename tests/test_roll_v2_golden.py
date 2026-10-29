"""Versioned native migration oracle: real Python HTTP, SQL and durable state."""

import json
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, create_refresh_token, revoke_token
from app.config import get_reading_execution_settings
from app.main import app
from app.models import Event, Issue, ReadingSession, Snapshot, Thread, User
from app.models.custom_cbl import CustomCBLEntry, CustomCBLList, CustomCBLOverlapDecision
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.schemas.roll_v2 import RollV2BootstrapResponse

FIXTURES = Path(__file__).parent / "fixtures" / "roll-v2" / "v1"
NOW = datetime(2026, 1, 4, 12, tzinfo=UTC)
D1 = datetime(2026, 1, 1, tzinfo=UTC)
CASES = (
    "new_session",
    "existing_session",
    "no_eligible",
    "pending",
    "snoozed",
    "skipped",
    "manual_die",
    "auto_die",
    "last_read",
    "recovery",
    "strict",
    "loose",
    "timezone_valid",
    "timezone_invalid",
    "timezone_preserved",
    "overlap",
)


class FrozenDatetime(datetime):
    """Freeze Python decision clocks without changing stored wire timestamps."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FrozenDatetime:
        """Return the fixed oracle instant in the requested timezone."""
        fixed = NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
        return cls(
            fixed.year,
            fixed.month,
            fixed.day,
            fixed.hour,
            fixed.minute,
            fixed.second,
            tzinfo=fixed.tzinfo,
        )


def _canonical(value: object, ids: dict[str, dict[int, int]], context: str = "") -> object:
    """Replace only generated primary keys; retain every response field and value."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_canonical(item, ids, context) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        domain = None
        if context == "thread_states":
            result[str(ids["thread"][int(key)])] = _canonical(item, ids, "thread")
            continue
        if key == "id":
            domain = "issue" if context in ("issue", "issue_states", "issues") else "thread"
        elif key == "user_id":
            domain = "user"
        elif key == "session_id":
            domain = "session"
        elif key.endswith("thread_id") or key == "thread_id":
            domain = "thread"
        elif key.endswith("issue_id"):
            domain = "issue"
        elif key == "source_id":
            domain = str(value.get("source_type"))
        elif key == "node_id":
            domain = str(value.get("node_type"))
        if domain and isinstance(item, int):
            result[key] = ids[domain][item]
        elif key in ("skipped_thread_ids", "snoozed_thread_ids") and isinstance(item, list):
            result[key] = [ids["thread"][entry] for entry in item]
        elif key in ("causing_issue_ids", "causing_member_issue_ids") and isinstance(item, list):
            result[key] = [ids["issue"][entry] for entry in item]
        else:
            result[key] = _canonical(item, ids, str(key))
    return result


async def _make_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    issue_count: int,
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create an owned thread with contiguous issues and a next pointer."""
    thread = Thread(
        user_id=user.id,
        title=title,
        format="Comic",
        issues_remaining=issue_count - read_through,
        total_issues=issue_count,
        queue_position=queue_position,
        status="active",
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position in range(1, issue_count + 1):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="read" if position <= read_through else "unread",
            read_at=D1 if position <= read_through else None,
        )
        db.add(issue)
        issues.append(issue)
    await db.flush()
    if issue_count and read_through < issue_count:
        thread.next_unread_issue_id = issues[read_through].id
    await db.flush()
    return thread, issues


async def _state(db: AsyncSession, owner: int) -> dict[str, object]:
    """Capture session writes and event/snapshot counts across an HTTP read."""
    sessions = (
        await db.scalars(
            select(ReadingSession)
            .where(ReadingSession.user_id == owner)
            .order_by(ReadingSession.id)
            .execution_options(populate_existing=True)
        )
    ).all()
    return {
        "sessions": [
            {
                key: getattr(row, key)
                for key in (
                    "started_at",
                    "ended_at",
                    "manual_die",
                    "start_die",
                    "timezone",
                    "bandwidth_source",
                    "active_bandwidth",
                    "predicted_bandwidth",
                    "pending_thread_id",
                    "pending_issue_id",
                    "pending_thread_updated_at",
                    "snoozed_thread_ids",
                    "skipped_thread_ids",
                    "bandwidth_confidence",
                    "bandwidth_version",
                    "bandwidth_updated_at",
                    "active_intent",
                    "predicted_intent",
                    "intent_confidence",
                    "intent_source",
                    "intent_version",
                    "session_mode_correction_guidance",
                )
            }
            for row in sessions
        ],
        "threads": [
            {
                key: getattr(row, key)
                for key in (
                    "id",
                    "queue_position",
                    "status",
                    "total_issues",
                    "issues_remaining",
                    "next_unread_issue_id",
                    "reading_progress",
                    "last_rating",
                    "last_activity_at",
                )
            }
            for row in (
                await db.scalars(
                    select(Thread)
                    .where(Thread.user_id == owner)
                    .order_by(Thread.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        ],
        "events": await db.scalar(select(func.count()).select_from(Event)),
        "snapshots": [
            {
                key: getattr(row, key)
                for key in (
                    "description",
                    "snapshot_kind",
                    "schema_version",
                    "thread_states",
                    "session_state",
                )
            }
            for row in (await db.scalars(select(Snapshot).order_by(Snapshot.id))).all()
        ],
        "issues": [
            {"id": row.id, "status": row.status, "read_at": row.read_at}
            for row in (await db.scalars(select(Issue).order_by(Issue.id))).all()
        ],
    }


@pytest.mark.parametrize("case", CASES)
async def test_python_bootstrap_golden(
    case: str,
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare complete HTTP JSON and before/after state to reviewed synthetic goldens."""
    for module in (
        "comic_pile.reading_session",
        "comic_pile.bandwidth",
        "app.services.roll_service",
        "app.models.reading_session",
        "app.models.snapshot",
    ):
        monkeypatch.setattr(f"{module}.datetime", FrozenDatetime)
    monkeypatch.setenv("OPTION_E_ENABLED", "true")
    monkeypatch.setenv("OPTION_E_APPROVED_PREVIEW", "local-test-fixture-no-production-approval")
    get_reading_execution_settings.cache_clear()
    try:
        await _run_case(case, auth_client, async_db, default_user)
    finally:
        get_reading_execution_settings.cache_clear()


async def _run_case(case: str, client: AsyncClient, db: AsyncSession, user: User) -> None:
    """Seed one small deterministic library and exercise the production route twice."""
    threads = []
    issues = []
    if case != "no_eligible":
        for position, title in enumerate(("Alpha", "Beta"), 1):
            thread, children = await _make_thread(
                db,
                user,
                title=title,
                issue_count=2,
                queue_position=position,
            )
            thread.created_at = NOW
            thread.last_activity_at = NOW
            threads.append(thread)
            issues.extend(children)
    reading_session = None
    if case != "new_session":
        reading_session = ReadingSession(user_id=user.id, started_at=NOW, start_die=6)
        db.add(reading_session)
        await db.flush()
        if case == "manual_die":
            reading_session.manual_die = 4
        if case in ("pending", "recovery"):
            reading_session.pending_thread_id = threads[1].id
            reading_session.pending_issue_id = issues[2].id
            reading_session.pending_thread_updated_at = NOW
        if case == "snoozed":
            reading_session.snoozed_thread_ids = [threads[0].id]
        if case == "skipped":
            reading_session.skipped_thread_ids = [threads[0].id]
        if case == "timezone_preserved":
            reading_session.timezone = "Asia/Tokyo"
        if case in ("auto_die", "last_read"):
            db.add(
                Event(
                    type="rate",
                    session_id=reading_session.id,
                    thread_id=threads[0].id,
                    issue_id=issues[0].id,
                    issue_number="1",
                    timestamp=NOW,
                    rating=4.0,
                    die_after=8,
                )
            )
            issues[0].status = "read"
            issues[0].read_at = NOW
    if case in ("strict", "loose", "recovery", "overlap"):
        reading_list = CustomCBLList(
            user_id=user.id,
            name="Synthetic order",
            mode="loose" if case == "loose" else "strict",
        )
        db.add(reading_list)
        await db.flush()
        db.add_all(
            [
                CustomCBLEntry(list_id=reading_list.id, issue_id=issues[0].id, position=1),
                CustomCBLEntry(list_id=reading_list.id, issue_id=issues[2].id, position=2),
            ]
        )
    if case == "overlap":
        volumes = [
            ExternalIdentity(provider="comicvine", entity_type="series", external_id=key)
            for key in ("9001", "9002")
        ]
        db.add_all(volumes)
        await db.flush()
        db.add_all(
            [
                ThreadExternalSeriesMapping(
                    thread_id=thread.id,
                    external_identity_id=volume.id,
                    status="confirmed",
                    evidence_source="test",
                )
                for thread, volume in zip(threads, volumes, strict=True)
            ]
        )
        db.add(
            CustomCBLOverlapDecision(
                user_id=user.id,
                list_id=reading_list.id,
                continuing_external_identity_id=volumes[1].id,
                waiting_external_identity_id=volumes[0].id,
            )
        )
    await db.flush()
    ids = {
        "user": {user.id: 1},
        "thread": {row.id: i for i, row in enumerate(threads, 1)},
        "issue": {row.id: i for i, row in enumerate(issues, 1)},
        "session": {},
    }
    before = await _state(db, user.id)
    timezone = {
        "timezone_valid": " America/Chicago ",
        "timezone_invalid": "Not/A_Zone",
        "timezone_preserved": "America/Chicago",
    }.get(case)
    response = await client.get(
        "/api/v2/roll/bootstrap",
        params={"timezone": timezone} if timezone else {},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    ids["session"][payload["session_id"]] = 1
    RollV2BootstrapResponse.model_validate(payload)
    after = await _state(db, user.id)
    repeat = await client.get("/api/v2/roll/bootstrap")
    assert repeat.status_code == 200
    assert repeat.json() == payload
    assert await _state(db, user.id) == after
    actual = {
        "contract_version": 1,
        "request": {
            "method": "GET",
            "path": "/api/v2/roll/bootstrap",
            "query": {"timezone": timezone} if timezone else {},
        },
        "status": response.status_code,
        "response": _canonical(payload, ids),
        "before": _canonical(before, ids),
        "after": _canonical(after, ids),
    }
    expected = json.loads((FIXTURES / f"{case}.json").read_text())
    assert actual == expected


def test_uses_existing_openapi_contract() -> None:
    """Keep the native oracle anchored to the existing public OpenAPI operation."""
    operation = app.openapi()["paths"]["/api/v2/roll/bootstrap"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RollV2BootstrapResponse",
    }
    assert [parameter["name"] for parameter in operation["parameters"]] == ["timezone"]
    assert operation["security"] == [{"HTTPBearer": []}]


@pytest.mark.parametrize(
    "case",
    (
        "missing",
        "malformed",
        "expired",
        "refresh",
        "revoked",
        "deleted",
        "missing_jti",
        "password_changed",
    ),
)
async def test_auth_failure_golden(
    case: str,
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """Freeze auth status, headers and errors without creating reading-history rows."""
    token = create_access_token({"sub": default_user.username, "jti": "golden-auth"})
    if case == "missing":
        del auth_client.headers["Authorization"]
    else:
        if case == "malformed":
            token = "synthetic-invalid-token"
        elif case == "expired":
            token = create_access_token(
                {"sub": default_user.username, "jti": "golden-auth"},
                expires_delta=timedelta(days=-1),
            )
        elif case == "refresh":
            token = create_refresh_token({"sub": default_user.username, "jti": "golden-auth"})
        elif case == "revoked":
            await revoke_token(async_db, token, default_user.id)
        elif case == "deleted":
            token = create_access_token({"sub": "synthetic-deleted-user", "jti": "golden-auth"})
        elif case == "missing_jti":
            token = create_access_token({"sub": default_user.username})
        elif case == "password_changed":
            default_user.password_changed_at = NOW
            await async_db.flush()
        auth_client.headers["Authorization"] = f"Bearer {token}"
    before = await _state(async_db, default_user.id)
    response = await auth_client.get("/api/v2/roll/bootstrap")
    assert response.status_code in (401, 403)
    assert await _state(async_db, default_user.id) == before
    actual = {
        "contract_version": 1,
        "status": response.status_code,
        "response": response.json(),
        "www_authenticate": response.headers.get("www-authenticate"),
        "sets_refresh_cookie": any(
            "refresh_token=" in header for header in response.headers.get_list("set-cookie")
        ),
    }
    assert actual == json.loads((FIXTURES / f"auth_{case}.json").read_text())


async def test_oracle_detects_live_queue_mutation(
    async_db: AsyncSession, default_user: User
) -> None:
    """Changing live queue order must change evidence even without a new snapshot."""
    thread, _ = await _make_thread(
        async_db, default_user, title="Queue guard", issue_count=1, queue_position=1
    )
    before = await _state(async_db, default_user.id)
    thread.queue_position = 2
    await async_db.flush()
    after = await _state(async_db, default_user.id)
    assert before["threads"] != after["threads"]
    assert before["snapshots"] == after["snapshots"]
