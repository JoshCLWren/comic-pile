"""Regression tests for screen-specific API response contracts."""

from typing import cast

from app.main import app
from app.schemas.session import SessionListItem, SessionResponse
from app.schemas.thread import QueueThreadListItem, ThreadDetail, ThreadResponse


QUEUE_FIELDS = {
    "id",
    "title",
    "format",
    "issues_remaining",
    "queue_position",
    "status",
    "last_activity_at",
    "is_blocked",
    "blocking_reasons",
    "collection_id",
    "total_issues",
    "next_unread_issue_number",
    "notes",
    "created_at",
}
QUEUE_DROPPED_FIELDS = {
    "last_rating",
    "review_url",
    "last_review_at",
    "is_test",
    "reading_progress",
    "next_unread_issue_id",
}
SESSION_HISTORY_FIELDS = {
    "id",
    "started_at",
    "ended_at",
    "start_die",
    "manual_die",
    "user_id",
    "ladder_path",
    "active_thread",
    "current_die",
    "last_rolled_result",
    "has_restore_point",
    "snapshot_count",
}
SESSION_HISTORY_DROPPED_FIELDS = {
    "snoozed_thread_ids",
    "snoozed_threads",
    "pending_thread_id",
}


def _response_schema(path: str) -> dict[str, object]:
    """Return the successful GET response schema for an OpenAPI path."""
    schema = app.openapi()["paths"][path]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    return cast(dict[str, object], schema)


def test_queue_item_contract_is_exact_and_measurably_narrower() -> None:
    """Queue items expose only the documented 14-field screen contract."""
    full_fields = set(ThreadResponse.model_fields)
    queue_fields = set(QueueThreadListItem.model_fields)

    assert queue_fields == QUEUE_FIELDS
    assert full_fields - queue_fields == QUEUE_DROPPED_FIELDS
    assert len(full_fields) == 20
    assert len(queue_fields) == 14
    assert (len(full_fields) - len(queue_fields)) / len(full_fields) == 0.30


def test_session_history_item_contract_is_exact_and_measurably_narrower() -> None:
    """History items expose only the documented 12-field screen contract."""
    full_fields = set(SessionResponse.model_fields)
    history_fields = set(SessionListItem.model_fields)

    assert history_fields == SESSION_HISTORY_FIELDS
    assert full_fields - history_fields == SESSION_HISTORY_DROPPED_FIELDS
    assert len(full_fields) == 15
    assert len(history_fields) == 12
    assert (len(full_fields) - len(history_fields)) / len(full_fields) == 0.20


def test_thread_detail_preserves_the_complete_thread_contract() -> None:
    """Thread detail remains a named compatibility contract with every full field."""
    assert set(ThreadDetail.model_fields) == set(ThreadResponse.model_fields)
    assert len(ThreadDetail.model_fields) == 20


def test_routes_publish_the_screen_specific_openapi_contracts() -> None:
    """The three affected GET routes advertise their intended response models."""
    assert _response_schema("/api/threads/") == {
        "$ref": "#/components/schemas/QueueThreadListResponse"
    }
    assert _response_schema("/api/threads/{thread_id}") == {
        "$ref": "#/components/schemas/ThreadDetail"
    }
    assert _response_schema("/api/sessions/") == {
        "$ref": "#/components/schemas/SessionHistoryListResponse"
    }
