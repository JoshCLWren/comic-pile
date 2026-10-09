"""Exclusion transparency for issue #3125: every non-rollable series is explained."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import roll as roll_api
from app.models import Issue, Thread
from app.schemas import RollBootstrapResponse, RollBootstrapThread, SessionMode
from app.schemas.session import SessionBandwidthState
from tests.conftest import get_or_create_user_async


class _Result:
    """Minimal SQLAlchemy result double for the bootstrap query sequence."""

    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self


def _mode_session(**kwargs):
    """Build a session double carrying every bootstrap-exposed mode attribute."""
    mode_fields = {
        "manual_die": None,
        "pending_thread_id": None,
        "snoozed_thread_ids": [],
        "skipped_thread_ids": [],
        "active_bandwidth": None,
        "predicted_bandwidth": None,
        "bandwidth_confidence": None,
        "bandwidth_source": None,
        "bandwidth_version": None,
        "active_intent": None,
        "predicted_intent": None,
        "intent_confidence": None,
        "intent_source": None,
        "intent_version": None,
        "session_mode_correction_guidance": None,
    }
    return SimpleNamespace(**{**mode_fields, **kwargs})


@pytest.mark.asyncio
async def test_bootstrap_excludes_and_explains_completed_series(monkeypatch):
    """Completed series vanish from the pool but are surfaced with a reason."""
    current_session = _mode_session(id=55, timezone=None)
    current_user = SimpleNamespace(id=7)

    rollable = SimpleNamespace(
        id=1, title="Rollable Series", format="ongoing", issue_id=None, issue_number=None, route_labels=[]
    )
    completed = SimpleNamespace(
        id=2, title="Completed Series", format="ongoing", status="completed", queue_position=5
    )
    stale_active = SimpleNamespace(
        id=3, title="Still Active", format="ongoing", status="active", queue_position=2
    )

    monkeypatch.setattr(roll_api, "get_or_create", AsyncMock(return_value=current_session))
    monkeypatch.setattr(roll_api, "get_session_with_thread_safe", AsyncMock(return_value=(current_session, None)))
    monkeypatch.setattr(roll_api, "get_current_die_for_session", AsyncMock(return_value=6))
    monkeypatch.setattr(roll_api, "derive_cross_session_excluded_thread_ids", AsyncMock(return_value=set()))

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[rollable, stale_active]),  # pool query (die-limited)
        _Result(scalar_value=0),                  # blocked count
        _Result(rows=[]),                         # blocked threads
        _Result(scalar_value=0),                  # stale count
        _Result(rows=[rollable, completed, stale_active]),  # all active threads
        _Result(rows=[completed]),                # completed threads
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db, timezone=None)

    # Counts are consistent and complete.
    assert response.total_threads == 3
    assert response.available_threads == 2
    assert response.excluded_count == 1
    assert response.inactive_count == 1
    assert len(response.excluded_threads) == 1
    assert len(response.inactive_threads) == 1

    # The completed series carries a reason the user understands.
    [excl] = response.excluded_threads
    assert excl.thread_id == completed.id
    assert excl.title == completed.title
    assert excl.format == completed.format
    assert excl.reason == "completed"
    assert excl.detail == "Read the full series"

    assert response.inactive_threads[0].reason == "completed"


@pytest.mark.asyncio
async def test_bootstrap_explains_not_in_queue_series(monkeypatch):
    """Active series with queue_position < 1 are excluded and labeled."""
    current_session = _mode_session(id=55, timezone=None)
    current_user = SimpleNamespace(id=7)

    rollable = SimpleNamespace(
        id=1, title="Rollable Series", format="ongoing", issue_id=None, issue_number=None, route_labels=[]
    )
    not_in_queue = SimpleNamespace(
        id=2, title="Deprioritized", format="ongoing", status="active", queue_position=0
    )

    monkeypatch.setattr(roll_api, "get_or_create", AsyncMock(return_value=current_session))
    monkeypatch.setattr(roll_api, "get_session_with_thread_safe", AsyncMock(return_value=(current_session, None)))
    monkeypatch.setattr(roll_api, "get_current_die_for_session", AsyncMock(return_value=6))
    monkeypatch.setattr(roll_api, "derive_cross_session_excluded_thread_ids", AsyncMock(return_value=set()))

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[rollable]),  # pool
        _Result(scalar_value=0),   # blocked count
        _Result(rows=[]),          # blocked threads
        _Result(scalar_value=0),   # stale count
        _Result(rows=[rollable, not_in_queue]),  # all active
        _Result(rows=[]),          # completed
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db, timezone=None)

    assert response.total_threads == 2
    assert response.available_threads == 1
    assert response.excluded_count == 1
    assert response.inactive_count == 1
    [excl] = response.excluded_threads
    assert excl.reason == "not_in_queue"
    assert excl.detail == "Not in the active queue"
    assert response.inactive_threads[0].reason == "not_in_queue"


@pytest.mark.asyncio
async def test_bootstrap_includes_multiple_inactive_series(monkeypatch):
    """Mixed completed + not-in-queue series all appear in the inactive list."""
    current_session = _mode_session(id=55, timezone=None)
    current_user = SimpleNamespace(id=7)

    rollable_a = SimpleNamespace(
        id=1, title="Rollable A", format="ongoing", issue_id=None, issue_number=None, route_labels=[]
    )
    completed_b = SimpleNamespace(id=2, title="Done B", format="ongoing", status="completed", queue_position=1)
    not_in_queue_c = SimpleNamespace(id=3, title="Moved Down C", format="ongoing", status="active", queue_position=-1)

    monkeypatch.setattr(roll_api, "get_or_create", AsyncMock(return_value=current_session))
    monkeypatch.setattr(roll_api, "get_session_with_thread_safe", AsyncMock(return_value=(current_session, None)))
    monkeypatch.setattr(roll_api, "get_current_die_for_session", AsyncMock(return_value=6))
    monkeypatch.setattr(roll_api, "derive_cross_session_excluded_thread_ids", AsyncMock(return_value=set()))

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[rollable_a]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[rollable_a, completed_b, not_in_queue_c]),
        _Result(rows=[completed_b]),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db, timezone=None)

    assert response.total_threads == 3
    assert response.available_threads == 1
    assert response.excluded_count == 2
    assert response.inactive_count == 2
    reasons = sorted(r.reason for r in response.excluded_threads)
    assert reasons == ["completed", "not_in_queue"]
    inactive_reasons = sorted(r.reason for r in response.inactive_threads)
    assert inactive_reasons == ["completed", "not_in_queue"]


@pytest.mark.asyncio
async def test_bootstrap_exclusion_counts_remain_consistent(monkeypatch):
    """total - available equals the union of all excluded reasons."""
    current_session = _mode_session(id=55, timezone=None)
    current_user = SimpleNamespace(id=7)

    rollable = SimpleNamespace(
        id=1, title="Rollable", format="ongoing", issue_id=None, issue_number=None, route_labels=[]
    )
    completed = SimpleNamespace(id=2, title="Done", format="ongoing", status="completed", queue_position=1)
    not_in_queue = SimpleNamespace(id=3, title="Low", format="ongoing", status="active", queue_position=0)

    monkeypatch.setattr(roll_api, "get_or_create", AsyncMock(return_value=current_session))
    monkeypatch.setattr(roll_api, "get_session_with_thread_safe", AsyncMock(return_value=(current_session, None)))
    monkeypatch.setattr(roll_api, "get_current_die_for_session", AsyncMock(return_value=6))
    monkeypatch.setattr(roll_api, "derive_cross_session_excluded_thread_ids", AsyncMock(return_value=set()))

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[rollable]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[rollable, completed, not_in_queue]),
        _Result(rows=[completed]),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db, timezone=None)

    assert response.total_threads - response.available_threads == response.excluded_count == 2


@pytest.mark.asyncio
async def test_bootstrap_schema_bounds_excluded_lists_without_losing_counts(monkeypatch):
    """Bounded lists keep the complete counts so the page never lies."""
    summaries = [
        RollBootstrapThread(id=index, title=f"Thread {index}", format="ongoing")
        for index in range(1, 26)
    ]

    response = RollBootstrapResponse(
        session_id=1,
        user_id=1,
        current_die=100,
        manual_die=None,
        pending_thread_id=None,
        last_rolled_result=None,
        session_mode=SessionMode(),
        active_thread=None,
        bandwidth=SessionBandwidthState(
            predicted_bandwidth=None,
            active_bandwidth=None,
            confidence=None,
            source=None,
            mode_version=None,
        ),
        roll_pool=summaries,
        snoozed_threads=summaries,
        snoozed_count=len(summaries),
        skipped_thread_ids=[],
        skipped_threads=[],
        blocked_count=len(summaries),
        blocked_threads=summaries,
        stale_thread_count=0,
        stale_thread=None,
        total_threads=len(summaries),
        available_threads=len(summaries),
        excluded_count=0,
        excluded_threads=[],
        inactive_count=0,
        inactive_threads=[],
    )

    assert len(response.excluded_threads) <= response.summary_limit
    assert len(response.inactive_threads) <= response.summary_limit
    assert response.excluded_count == 0
    assert response.inactive_count == 0
