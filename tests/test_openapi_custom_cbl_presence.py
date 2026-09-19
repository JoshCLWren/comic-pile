"""Regression check for Custom CBL routes in the generated OpenAPI schema."""

import json
from pathlib import Path


def test_custom_cbl_routes_present_in_openapi():
    """Verify all Custom CBL routes are present in the generated OpenAPI document."""
    schema_path = Path("frontend/src/generated/openapi.json")
    assert schema_path.exists(), "openapi.json should exist"

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    paths = schema.get("paths", {})

    expected_paths = [
        "/api/v1/custom-cbls",
        "/api/v1/custom-cbls/issue-search",
        "/api/v1/custom-cbls/{list_id}",
        "/api/v1/custom-cbls/{list_id}/export",
        "/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply",
    ]

    for path in expected_paths:
        assert path in paths, f"Expected path {path} missing from OpenAPI schema"

