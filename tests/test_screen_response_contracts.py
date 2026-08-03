"""Regression tests for screen-specific API response contracts."""

from typing import cast

from app.main import app
from app.schemas.dependency import BlockingExplanation, ThreadDependenciesResponse
from app.schemas.issue import IssueListResponse, IssueResponse
from app.schemas.roll import RollResponse
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
ISSUE_FIELDS = {
    "id",
    "thread_id",
    "issue_number",
    "position",
    "status",
    "read_at",
    "created_at",
}
BLOCKING_EXPLANATION_FIELDS = {
    "is_blocked",
    "blocking_reasons",
}
THREAD_DEPENDENCIES_FIELDS = {
    "blocking",
    "blocked_by",
}


def _response_schema(
    path: str,
    method: str = "get",
) -> dict[str, object]:
    """Return the successful response schema for an OpenAPI path."""
    schema = app.openapi()["paths"][path][method]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    return cast(dict[str, object], schema)


def _component_schema(name: str) -> dict[str, object]:
    """Return a named component schema from the OpenAPI document."""
    schema = app.openapi()["components"]["schemas"][name]
    return cast(dict[str, object], schema)


def test_queue_item_contract_is_exact_and_measurably_narrower() -> None:
    """Queue items expose only the documented 13-field screen contract."""
    full_fields = set(ThreadResponse.model_fields)
    queue_fields = set(QueueThreadListItem.model_fields)

    assert queue_fields == QUEUE_FIELDS
    assert full_fields - queue_fields == QUEUE_DROPPED_FIELDS
    assert len(full_fields) == 19
    assert len(queue_fields) == 13
    assert (len(full_fields) - len(queue_fields)) / len(full_fields) == 6 / 19


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
    assert len(ThreadDetail.model_fields) == 19


def test_issue_list_item_contract_is_exact_and_named() -> None:
    """Issue-list items expose only the documented 7-field screen contract."""
    assert set(IssueResponse.model_fields) == ISSUE_FIELDS
    assert len(IssueResponse.model_fields) == 7
    assert set(IssueListResponse.model_fields) == {
        "issues",
        "next_page_token",
        "page_size",
        "total_count",
    }


def test_blocked_summary_contract_is_exact_and_named() -> None:
    """Blocked-summary responses expose only the documented screen contract."""
    assert set(BlockingExplanation.model_fields) == BLOCKING_EXPLANATION_FIELDS
    assert set(ThreadDependenciesResponse.model_fields) == THREAD_DEPENDENCIES_FIELDS


def test_roll_screen_contract_is_named_and_bounded() -> None:
    """The Roll screen response is a named, bounded contract without thread detail fields."""
    roll_fields = set(RollResponse.model_fields)
    assert "title" in roll_fields
    assert "format" in roll_fields
    assert "result" in roll_fields
    assert "die_size" in roll_fields
    assert "issues_remaining" in roll_fields
    assert "queue_position" in roll_fields
    assert "offset" in roll_fields
    assert "snoozed_count" in roll_fields
    assert len(roll_fields) == 15


def test_current_session_contract_is_named() -> None:
    """The current-session screen uses the named SessionResponse contract."""
    assert set(SessionResponse.model_fields) >= {
        "id",
        "active_thread",
        "current_die",
        "start_die",
        "ladder_path",
        "snoozed_thread_ids",
        "snoozed_threads",
        "pending_thread_id",
        "snapshot_count",
        "has_restore_point",
    }


def test_routes_publish_the_screen_specific_openapi_contracts() -> None:
    """Affected retained routes advertise their intended response models."""
    assert _response_schema("/api/threads/") == {
        "$ref": "#/components/schemas/QueueThreadListResponse"
    }
    assert _response_schema("/api/threads/{thread_id}") == {
        "$ref": "#/components/schemas/ThreadDetail"
    }
    assert _response_schema("/api/sessions/") == {
        "$ref": "#/components/schemas/SessionHistoryListResponse"
    }
    assert _response_schema("/api/sessions/current/") == {
        "$ref": "#/components/schemas/SessionResponse"
    }
    assert _response_schema("/api/v1/threads/{thread_id}/issues") == {
        "$ref": "#/components/schemas/IssueListResponse"
    }
    assert _response_schema("/api/v1/threads/{thread_id}/dependencies") == {
        "$ref": "#/components/schemas/ThreadDependenciesResponse"
    }
    assert _response_schema("/api/roll/", method="post") == {
        "$ref": "#/components/schemas/RollResponse"
    }
    assert _response_schema(
        "/api/v1/threads/{thread_id}:getBlockingInfo",
        method="post",
    ) == {"$ref": "#/components/schemas/BlockingExplanation"}


def test_no_collection_specific_contracts_remain_in_openapi() -> None:
    """No collection-specific response model or route survives in the OpenAPI document."""
    schema = app.openapi()
    collection_paths = [
        path for path in schema["paths"] if "collection" in path.lower()
    ]
    collection_schemas = [
        name
        for name in schema["components"]["schemas"]
        if "collection" in name.lower()
    ]
    assert collection_paths == []
    assert collection_schemas == []


def test_component_schemas_expose_exact_screen_contracts() -> None:
    """Named component schemas advertise the bounded list models, not detail models."""
    assert set(_component_schema("QueueThreadListItem")["properties"]) == QUEUE_FIELDS
    assert set(_component_schema("IssueResponse")["properties"]) == ISSUE_FIELDS
    assert (
        set(_component_schema("BlockingExplanation")["properties"])
        == BLOCKING_EXPLANATION_FIELDS
    )
