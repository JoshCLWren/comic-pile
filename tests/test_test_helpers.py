"""Regression tests for test-only browser helpers."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.test_helpers import (
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

    response = await expire_current_session(SimpleNamespace(id=1), db)

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
        {"name": "Beta", "items": [{"thread_id": 1, "position": 2}]},
        SimpleNamespace(id=1),
        db,
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
        {"issue_id": 12, "series_name": "Fixtureverse", "series_id": 612001},
        SimpleNamespace(id=99),
        db,
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
        {"thread_id": 5, "series_name": "Crossed Paths"},
        SimpleNamespace(id=7),
        db,
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
            {"issue_id": 30},
            SimpleNamespace(id=99),
            db,
        )
    assert exc_info.value.status_code == 404
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_test_issue_identity_requires_scope_target() -> None:
    """Missing both issue_id and thread_id must fail fast."""
    db = AsyncMock(spec=AsyncSession)
    with pytest.raises(HTTPException) as exc_info:
        await create_test_issue_identity({}, SimpleNamespace(id=1), db)
    assert exc_info.value.status_code == 400
    db.execute.assert_not_awaited()
