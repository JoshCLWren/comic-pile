"""Tests for production-to-local export safety validation."""

from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.verify_clone_export import ExportValidationError, validate_export


def _valid_export() -> dict[str, object]:
    """Return a minimal internally consistent clone export."""
    return {
        "schema_version": "1.0",
        "exported_at": "2026-08-04T00:00:00+00:00",
        "source_url": "example.invalid:5432/comic_pile",
        "source_username": "Josh",
        "user": {"id": 1, "username": "Josh", "email": "josh@example.com"},
        "threads": [
            {
                "id": 10,
                "user_id": 1,
                "title": "Example",
                "next_unread_issue_id": 20,
            }
        ],
        "issues": [{"id": 20, "thread_id": 10, "issue_number": "1"}],
        "dependencies": [
            {"id": 30, "source_issue_id": 20, "target_issue_id": 20}
        ],
        "reading_orders": [{"id": 40, "user_id": 1, "name": "Order"}],
        "reading_order_items": [
            {"id": 50, "reading_order_id": 40, "thread_id": 10, "position": 1}
        ],
        "sessions": [
            {
                "id": 60,
                "user_id": 1,
                "pending_thread_id": 10,
                "pending_issue_id": 20,
                "snoozed_thread_ids": [10],
            }
        ],
        "events": [
            {
                "id": 70,
                "session_id": 60,
                "thread_id": 10,
                "selected_thread_id": 10,
                "issue_id": 20,
            }
        ],
        "snapshots": [{"id": 80, "session_id": 60, "event_id": 70}],
    }


def test_validate_export_accepts_consistent_retained_graph() -> None:
    """A complete retained-data graph returns deterministic table counts."""
    counts = validate_export(_valid_export())

    assert counts == {
        "threads": 1,
        "issues": 1,
        "dependencies": 1,
        "reading_orders": 1,
        "reading_order_items": 1,
        "sessions": 1,
        "events": 1,
        "snapshots": 1,
    }


@pytest.mark.parametrize("key", ["collections", "refresh_tokens", "auth_tokens"])
def test_validate_export_rejects_removed_or_sensitive_payloads(key: str) -> None:
    """Removed Collections and authentication payloads cannot enter local restore."""
    document = _valid_export()
    document[key] = []

    with pytest.raises(ExportValidationError, match="forbidden"):
        validate_export(document)


def test_validate_export_rejects_nested_secret_fields() -> None:
    """Secret-like fields are rejected even when nested in a retained record."""
    document = _valid_export()
    user = document["user"]
    assert isinstance(user, dict)
    user["password_hash"] = "should-never-be-exported"

    with pytest.raises(ExportValidationError, match="sensitive field"):
        validate_export(document)


def test_validate_export_rejects_duplicate_record_ids() -> None:
    """Duplicate IDs are rejected before import remapping can become ambiguous."""
    document = _valid_export()
    issues = document["issues"]
    assert isinstance(issues, list)
    issues.append(deepcopy(issues[0]))

    with pytest.raises(ExportValidationError, match="duplicate id 20"):
        validate_export(document)


def test_validate_export_rejects_broken_foreign_key() -> None:
    """References to absent retained records fail before any database mutation."""
    document = _valid_export()
    events = document["events"]
    assert isinstance(events, list)
    event = events[0]
    assert isinstance(event, dict)
    event["selected_thread_id"] = 999

    with pytest.raises(ExportValidationError, match="references missing id 999"):
        validate_export(document)


def test_validate_export_rejects_unknown_schema_version() -> None:
    """Unknown export versions fail closed instead of being guessed during restore."""
    document = _valid_export()
    document["schema_version"] = "2.0"

    with pytest.raises(ExportValidationError, match="unsupported schema_version"):
        validate_export(document)
