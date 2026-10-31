"""Frozen GET /api/v2/roll/bootstrap contract after the Python handler removal.

The live operation is served by native Rust ingress. The Python handler is
gone, so this test keeps the frozen OpenAPI snapshot and the frozen Python
schema from silently drifting apart. It also guards the Roll UI visibility
fields that the native response must keep returning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.roll_v2 import RollV2BootstrapResponse

CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "native"
    / "contracts"
    / "roll-bootstrap-v2.openapi.json"
)


def _contract() -> dict[str, Any]:
    """Load the frozen v2 operation snapshot."""
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_frozen_operation_is_the_v2_bootstrap_get() -> None:
    """The frozen operation keeps its path, response, parameter and security."""
    operation = _contract()["paths"]["/api/v2/roll/bootstrap"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RollV2BootstrapResponse",
    }
    assert [parameter["name"] for parameter in operation["parameters"]] == ["timezone"]
    assert operation["security"] == [{"HTTPBearer": []}]


def test_frozen_contract_contains_only_the_supported_v2_path() -> None:
    """The retired v1 and legacy bootstrap paths are not part of this contract."""
    paths = _contract()["paths"]

    assert list(paths) == ["/api/v2/roll/bootstrap"]
    assert "get" in paths["/api/v2/roll/bootstrap"]


def test_frozen_python_schema_matches_the_contract() -> None:
    """The retained Python DTO still describes the frozen v2 response."""
    schema = _contract()["components"]["schemas"]["RollV2BootstrapResponse"]

    assert set(schema["properties"]) == set(RollV2BootstrapResponse.model_fields)


def test_frozen_contract_preserves_roll_ui_visibility_fields() -> None:
    """Candidate tags and excluded/inactive details stay in the v2 contract."""
    components = _contract()["components"]["schemas"]
    properties = components["RollV2BootstrapResponse"]["properties"]

    for name in (
        "rollable",
        "last_read",
        "total_threads",
        "available_threads",
        "excluded_count",
        "excluded_threads",
        "inactive_count",
        "inactive_threads",
        "snoozed_threads",
        "skipped_threads",
        "blocked_threads",
        "stale_thread",
    ):
        assert name in properties, f"frozen v2 contract lost {name}"

    assert "tags" in components["RollableThread"]["properties"]
