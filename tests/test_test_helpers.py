"""Regression tests for test-only browser helpers."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)

from app.services.test_helpers import (
    create_test_cbl_source,
    create_test_issue_identity,
    create_test_reading_order,
    expire_current_session,
)


def _query_result(value: object) -> Mock:
    """Build a query result whose scalar/scalars accessors expose query values."""
    result = Mock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value = value if isinstance(value, list) else [value]
    return result


@pytest.mark.asyncio
async def test_expire_current_session_ends_active_session() -> None:
    """The helper must expire sessions even when recent reading activity exists."""
    session = SimpleNamespace(
        started_at=datetime.now(UTC),
        ended_at=None,
        pending_thread_id=17,
        pending_issue_id=42,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = session
    db = AsyncMock(spec=AsyncSession)
    db.execute.return_value = result

    response = await expire_current_session(db, user_id=1)

    assert response == {"status": "success", "message": "Session expired"}
    assert session.ended_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_test_reading_order_builds_order_and_items() -> None:
    """The helper must create a reading order plus any provided items."""
    db = AsyncMock(spec=AsyncSession)
    db.commit.return_value = None
    db.refresh.return_value = None
    db.add.side_effect = lambda obj: setattr(obj, "id", 7)

    response = await create_test_reading_order(
        db,
        user_id=1,
        payload={"name": "Beta", "items": [{"thread_id": 1, "position": 2}]},
    )

    assert response == {"id": 7, "name": "Beta"}
    db.add.assert_called()
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_test_issue_identity_confirms_identity_for_owned_issue() -> None:
    """Seeding an issue id must persist a confirmed identity plus mapping."""
    issue = SimpleNamespace(id=12, thread_id=4, position=1, issue_number="1")
    owner = SimpleNamespace(id=4, user_id=99)
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [
        _query_result(issue),
        _query_result(owner),
        _query_result(None),
        _query_result(None),
    ]
    db.flush.return_value = None
    db.commit.return_value = None

    response = await create_test_issue_identity(
        db,
        user_id=99,
        payload={"issue_id": 12, "series_name": "Fixtureverse", "series_id": 612001},
    )

    assert response == {
        "issue_ids": [12],
        "series_name": "Fixtureverse",
        "series_id": 612001,
    }
    db.commit.assert_awaited_once()

    adds = [call.args[0] for call in db.add.call_args_list]
    identity = next(add for add in adds if add.__class__.__name__ == "ExternalIdentity")
    assert identity.provider == "comicvine"
    assert identity.entity_type == "issue"
    assert identity.external_id.startswith("4000-")
    payload = identity.metadata_json["raw_provider_payload"]
    assert payload["volume"] == {"id": 612001, "name": "Fixtureverse"}
    assert payload["issue_number"] == "1"
    mapping = next(add for add in adds if add.__class__.__name__ == "IssueExternalIdentityMapping")
    assert mapping.status == "confirmed"
    assert mapping.issue_id == 12
    assert mapping.evidence_source == "e2e-fixture"


@pytest.mark.asyncio
async def test_create_test_issue_identity_seeds_every_thread_issue() -> None:
    """Seeding a thread id must re-identify every position-ordered issue."""
    thread = SimpleNamespace(id=5, user_id=7)
    issues = [
        SimpleNamespace(id=21, thread_id=5, position=2, issue_number="2"),
        SimpleNamespace(id=20, thread_id=5, position=1, issue_number="1"),
    ]
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [
        _query_result(thread),
        _query_result(issues),
        _query_result(None),
        _query_result(None),
        _query_result(None),
        _query_result(None),
    ]
    db.flush.return_value = None
    db.commit.return_value = None

    response = await create_test_issue_identity(
        db,
        user_id=7,
        payload={"thread_id": 5, "series_name": "Crossed Paths"},
    )
    assert response["issue_ids"] == [20, 21]

    adds = [call.args[0] for call in db.add.call_args_list]
    identities = [
        add for add in adds if add.__class__.__name__ == "ExternalIdentity"
    ]
    assert len(identities) == 2
    by_issue_number = {identity.metadata_json["issue_number"]: identity for identity in identities}
    assert by_issue_number["1"].metadata_json["volume"]["name"] == "Crossed Paths"
    assert by_issue_number["2"].metadata_json["volume"]["name"] == "Crossed Paths"
    mappings = [
        add for add in adds if add.__class__.__name__ == "IssueExternalIdentityMapping"
    ]
    assert [mapping.issue_id for mapping in mappings] == [20, 21]
    assert all(mapping.status == "confirmed" for mapping in mappings)


@pytest.mark.asyncio
async def test_create_test_issue_identity_rejects_unowned_issue() -> None:
    """An identity must never be seeded onto another user's issue."""
    issue = SimpleNamespace(id=30, thread_id=9, position=1, issue_number="1")
    owner = SimpleNamespace(id=9, user_id=1)
    db = AsyncMock(spec=AsyncSession)
    db.execute.side_effect = [
        _query_result(issue),
        _query_result(owner),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await create_test_issue_identity(
            db,
            user_id=99,
            payload={"issue_id": 30},
        )
    assert exc_info.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_test_issue_identity_requires_scope_target() -> None:
    """Missing both issue_id and thread_id must fail fast."""
    db = AsyncMock(spec=AsyncSession)
    with pytest.raises(HTTPException) as exc_info:
        await create_test_issue_identity(db, user_id=1, payload={})
    assert exc_info.value.status_code == 400
    db.execute.assert_not_awaited()


def _effective_route_paths(app: object) -> set[str]:
    """Collect effective route paths, descending into router-inclusion nodes.

    FastAPI 0.137+ keeps included routers as inclusion-tree nodes instead of
    flat route entries, so recurse through each node's original router while
    accumulating its mount prefix.

    Args:
        app: FastAPI application instance.

    Returns:
        Effective paths of every reachable route.
    """
    paths: set[str] = set()
    stack: list[tuple[object, str]] = [
        (route, "") for route in getattr(app, "routes", [])
    ]
    while stack:
        route, prefix = stack.pop(0)
        route_path = getattr(route, "path", None)
        if isinstance(route_path, str) and not hasattr(route, "original_router"):
            paths.add(f"{prefix}{route_path}")
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        nested_routes = getattr(original_router, "routes", None)
        if nested_routes is None or include_context is None:
            if isinstance(route_path, str):
                paths.add(f"{prefix}{route_path}")
            continue
        nested_prefix = f"{prefix}{getattr(include_context, 'prefix', '')}"
        stack[0:0] = [(nested, nested_prefix) for nested in nested_routes]
    return paths


@pytest.mark.asyncio
async def test_create_test_cbl_source_reuses_shared_comicvine_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeding many CBL sources must reuse one shared Comic Vine identity row."""
    from app.schemas.test_fixtures import TestCblSourceCreate, TestCblSourceEntryCreate

    monkeypatch.setenv("TEST_ENVIRONMENT", "true")
    identity = SimpleNamespace(id=88)
    issue = SimpleNamespace(id=12, thread_id=4)
    owner = SimpleNamespace(id=4, user_id=99)
    db = AsyncMock(spec=AsyncSession)
    # Statement order: identity upsert, identity re-select, issue select,
    # owner select, mapping upsert.
    db.execute.side_effect = [
        Mock(),
        _query_result(identity),
        _query_result(issue),
        _query_result(owner),
        Mock(),
    ]
    db.flush.return_value = None
    db.commit.return_value = None
    db.add.side_effect = lambda obj: setattr(obj, "id", 7)

    response = await create_test_cbl_source(
        db,
        user_id=99,
        payload=TestCblSourceCreate(
            name="Fixture Compare A",
            source_path="Fixtures/Compare A.cbl",
            content_hash="hash-a",
            revision_sha="rev-a",
            repository="fixture-repo-a",
            entries=[
                TestCblSourceEntryCreate(
                    position=1,
                    series_name="Compare Series",
                    issue_number="1",
                    issue_id=12,
                    comicvine_issue_id="4000-compare-a",
                )
            ],
        ),
    )

    assert response.entries[0].comicvine_issue_id == "4000-compare-a"
    added_types = [call.args[0].__class__.__name__ for call in db.add.call_args_list]
    assert "ExternalIdentity" not in added_types
    assert "IssueExternalIdentityMapping" not in added_types
    # The identity and mapping writes must be database-level upserts, not
    # check-then-create reads that can race under concurrent fixture calls:
    # identity upsert, identity re-select, issue, owner, mapping upsert.
    assert db.execute.await_count == 5


@pytest.mark.asyncio
async def test_create_test_cbl_source_upserts_shared_identity_concurrently(
    monkeypatch: pytest.MonkeyPatch,
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Two concurrent fixture calls sharing one Comic Vine ID must never race.

    The collector used to check-then-create the shared ExternalIdentity row, so
    two overlapping fixture calls could both pass the existence test and violate
    the unique constraint. The database-level upsert lets the losing call's
    insert no-op instead.
    """
    from app.models.external_identity import (
        ExternalIdentity,
        IssueExternalIdentityMapping,
    )
    from app.models.issue import Issue
    from app.models.thread import Thread
    from app.models.user import User
    from app.schemas.test_fixtures import TestCblSourceCreate, TestCblSourceEntryCreate

    monkeypatch.setenv("TEST_ENVIRONMENT", "true")

    owner = User(username="cbl-concurrency-user")
    async_db_committed.add(owner)
    await async_db_committed.flush()
    thread = Thread(
        title="Concurrency Thread",
        format="comic",
        issues_remaining=1,
        total_issues=1,
        queue_position=0,
        status="active",
        user_id=owner.id,
        reading_progress="unstarted",
    )
    async_db_committed.add(thread)
    await async_db_committed.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1)
    async_db_committed.add(issue)
    await async_db_committed.commit()

    payload = TestCblSourceCreate(
        name="Fixture Concurrency A",
        entries=[
            TestCblSourceEntryCreate(
                position=1,
                series_name="Concurrency Series",
                issue_number="1",
                issue_id=issue.id,
                comicvine_issue_id="4000-concurrency-shared",
            )
        ],
    )
    second_session_maker = async_sessionmaker(bind=db_engine, expire_on_commit=False)

    async with second_session_maker() as second_session:
        first_response, second_response = await asyncio.gather(
            create_test_cbl_source(
                async_db_committed,
                user_id=owner.id,
                payload=payload,
            ),
            create_test_cbl_source(
                second_session,
                user_id=owner.id,
                payload=payload,
            ),
        )

    assert first_response.id != second_response.id
    shared_id = "4000-concurrency-shared"
    assert first_response.entries[0].comicvine_issue_id == shared_id
    assert second_response.entries[0].comicvine_issue_id == shared_id

    identities_total = await async_db_committed.scalar(
        select(func.count())
        .select_from(ExternalIdentity)
        .where(ExternalIdentity.external_id == shared_id)
    )
    # Exactly one shared identity row survived two overlapping calls.
    assert identities_total == 1

    mappings_total = await async_db_committed.scalar(
        select(func.count()).select_from(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    )
    # Exactly one confirmed mapping survived two overlapping calls too.
    assert mappings_total == 1


def test_test_helper_routes_are_mounted_only_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The application factory exposes fixture routes only in test environments."""
    from app.main import create_app

    monkeypatch.delenv("TEST_ENVIRONMENT", raising=False)
    production_app = create_app(serve_frontend=False)
    production_paths = _effective_route_paths(production_app)
    assert not any(path.startswith("/api/test/") for path in production_paths)
    assert not {
        "/api/test/reading-orders",
        "/api/test/issue-identity",
        "/api/test/cbl-source",
        "/api/test/sessions/expire",
    } & set(production_app.openapi()["paths"])

    monkeypatch.setenv("TEST_ENVIRONMENT", "true")
    test_app = create_app(serve_frontend=False)
    test_paths = _effective_route_paths(test_app)
    assert {
        "/api/test/reading-orders",
        "/api/test/issue-identity",
        "/api/test/cbl-source",
        "/api/test/sessions/expire",
    } <= test_paths
    assert {
        "/api/test/reading-orders",
        "/api/test/issue-identity",
        "/api/test/cbl-source",
        "/api/test/sessions/expire",
    } <= set(test_app.openapi()["paths"])
