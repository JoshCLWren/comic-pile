"""Regression: conflicting strict CBL and natural issue order is not an opaque 500."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import get_app_settings
from app.exception_handlers import register_exception_handlers
from app.services.reading_list_cycle_validator import validate_reading_constraints
from app.services.reading_list_evaluator import (
    ReadingIssue,
    ReadingList,
    ReadingListEntry,
    ReadingSnapshot,
    ReadingThread,
)

#: Synthetic evaluator snapshot for the B.P.R.D. Hell on Earth cycle case. This
#: test never touches the database; the snapshot is a pure evaluator fixture, so
#: the reader id is a module constant referenced by name (see the
#: hardcoded-ID guard in tests/test_hardcoded_ids.py).
READER_ID = 1


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_persisted_bprd_cycle_returns_actionable_conflict(method: str) -> None:
    """A Julix-style cross-order cycle fails closed with issue-level evidence."""
    snapshot = ReadingSnapshot(
        user_id=READER_ID,
        threads=(ReadingThread(18874, name="B.P.R.D.: Hell on Earth"),),
        issues=(
            ReadingIssue(117477, 18874, 26),
            ReadingIssue(117478, 18874, 27),
            ReadingIssue(117474, 18874, 36),
            ReadingIssue(117475, 18874, 37),
        ),
        lists=(
            ReadingList(
                2,
                "strict",
                (
                    ReadingListEntry(117474),
                    ReadingListEntry(117475),
                    ReadingListEntry(117477),
                    ReadingListEntry(117478),
                ),
                name="Mignolaverse",
            ),
        ),
    )
    app = FastAPI()
    register_exception_handlers(app, get_app_settings())

    @app.api_route("/synthetic/bprd", methods=["GET", "PUT"])
    async def read_or_update_bprd() -> None:
        """Trigger the same stored constraint evaluation used by API readers."""
        validate_reading_constraints(snapshot)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, "/synthetic/bprd")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "reading_list_cycle"
    assert "reading list and series ordering conflict" in detail["message"]
    assert detail["truncated"] is False
    assert any("series order" in edge["origin"] for edge in detail["path"])
    assert any("strict order" in edge["origin"] for edge in detail["path"])
    assert {edge["source_issue_id"] for edge in detail["path"]}.issubset(
        {117474, 117475, 117477, 117478}
    )
