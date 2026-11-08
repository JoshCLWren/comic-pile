"""Guard the live transitional v2 success contracts from becoming opaque JSON.

``GET /api/v2/roll/bootstrap`` and ``POST /api/v2/reading-sessions`` remain
deployed native operations until their owning retirement work. Their success
bodies must stay typed in the generated client authority: the existing frontend
depends on known session, die, pending, mode, bandwidth, rollable, recovery,
read, snooze and skip fields. Transitional means bounded by a removal plan, not
unconstrained.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
GENERATED_SCHEMA: Final = ROOT / "frontend" / "src" / "generated" / "openapi.json"

EXPECTED_FIELDS: Final = {
    "BootstrapResponseV2": (
        "active_thread",
        "bandwidth",
        "last_read",
        "last_rolled_result",
        "pending_thread_id",
        "pool_reason",
        "roll_recovery",
        "rollable",
        "session_id",
        "session_mode",
        "skipped_thread_ids",
        "skipped_threads",
        "snoozed_count",
        "snoozed_threads",
        "timezone",
        "user_id",
    ),
    "BootstrapSessionMode": (
        "active_bandwidth",
        "active_intent",
        "bandwidth_confidence",
        "bandwidth_source",
        "bandwidth_version",
        "intent_confidence",
        "intent_source",
        "intent_version",
        "predicted_bandwidth",
        "predicted_intent",
        "session_mode_correction_guidance",
    ),
    "BootstrapBandwidth": (
        "active_bandwidth",
        "confidence",
        "mode_version",
        "predicted_bandwidth",
        "source",
    ),
    "BootstrapActiveThread": (
        "format",
        "id",
        "issue_id",
        "issue_number",
        "issues_read",
        "issues_remaining",
        "last_rating",
        "last_rolled_result",
        "next_issue_id",
        "next_issue_number",
        "queue_position",
        "reading_progress",
        "tags",
        "title",
        "total_issues",
    ),
    "BootstrapLastRead": (
        "cover_url",
        "issue_id",
        "issue_number",
        "read_at",
        "thread_id",
        "thread_title",
    ),
    "BootstrapThreadSummary": ("format", "id", "last_activity_at", "tags", "title"),
    "BootstrapTag": (
        "color",
        "created_at",
        "id",
        "name",
        "normalized_name",
        "owner_user_id",
        "scope",
        "updated_at",
    ),
    "BootstrapRollableItem": (
        "identity",
        "issue",
        "overflow_routes_count",
        "reader",
        "routes",
        "thread",
    ),
    "BootstrapIssueSummary": ("canonical_series_title", "cover_url", "id", "number"),
    "BootstrapIdentitySummary": (
        "canonical_series_id",
        "series_mapping_state",
        "source",
        "state",
    ),
    "BootstrapReaderStats": (
        "average_rating",
        "issue_count",
        "latest_rating",
        "progress_scope",
        "rating_count",
        "read_count",
    ),
    "BootstrapRoute": ("kind", "name"),
    "BootstrapRollRecovery": (
        "chains",
        "diagnostics",
        "direct_blockers",
        "original_thread_id",
        "original_thread_title",
        "readable_prerequisites",
    ),
    "ReadingSessionCreatedResponse": ("created", "session_id"),
}


def _object(value: object, context: str) -> dict[str, object]:
    """Narrow ``value`` to a string-keyed JSON object."""
    if not isinstance(value, dict):
        raise AssertionError(f"{context} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _load_schema() -> dict[str, object]:
    """Load the checked-in merged client schema."""
    value: object = json.loads(GENERATED_SCHEMA.read_text(encoding="utf-8"))
    return _object(value, GENERATED_SCHEMA.name)


def _success_schema_ref(document: dict[str, object], path: str, method: str) -> str:
    """Return the success-response ``$ref`` for one operation."""
    paths = _object(document.get("paths"), "paths")
    path_item = _object(paths.get(path), f"path {path}")
    operation = _object(path_item.get(method), f"{method} {path}")
    responses = _object(operation.get("responses"), f"{method} {path} responses")
    response = _object(responses.get("200"), f"{method} {path} 200")
    content = _object(response.get("content"), f"{method} {path} content")
    media = _object(content.get("application/json"), f"{method} {path} media")
    schema = _object(media.get("schema"), f"{method} {path} schema")
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        raise AssertionError(f"{method} {path} success body is not a typed reference")
    return ref


def _component_properties(document: dict[str, object], name: str) -> set[str]:
    """Return the declared property names for one component schema."""
    components = _object(document.get("components"), "components")
    schemas = _object(components.get("schemas"), "components.schemas")
    schema = _object(schemas.get(name), f"schema {name}")
    properties = _object(schema.get("properties"), f"schema {name} properties")
    return set(properties)


def test_transitional_success_bodies_are_typed() -> None:
    """Bootstrap and reading-session success bodies must not be arbitrary JSON."""
    document = _load_schema()

    assert (
        _success_schema_ref(document, "/api/v2/roll/bootstrap", "get")
        == "#/components/schemas/BootstrapResponseV2"
    )
    assert (
        _success_schema_ref(document, "/api/v2/reading-sessions", "post")
        == "#/components/schemas/ReadingSessionCreatedResponse"
    )


def test_transitional_success_bodies_keep_every_known_ui_field() -> None:
    """Fail when a field the live frontend reads disappears from the contract."""
    document = _load_schema()
    missing = {
        name: sorted(set(fields) - _component_properties(document, name))
        for name, fields in EXPECTED_FIELDS.items()
    }
    assert {name: fields for name, fields in missing.items() if fields} == {}
