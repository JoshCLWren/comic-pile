"""OpenAPI custom-CBL presence: only live endpoints remain."""

from pathlib import Path
import json


def test_custom_cbl_routes_present_in_openapi() -> None:
    """Pruned CRUD is absent; live search/export/apply are present."""
    schema = json.loads((Path(__file__).resolve().parents[1] / "frontend/src/generated/openapi.json").read_text(encoding="utf-8"))
    paths = schema["paths"]
    assert "/api/v1/custom-cbls/issue-search" in paths
    assert "/api/v1/custom-cbls/{list_id}/export" in paths
    assert "/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply" in paths
    assert "/api/v1/custom-cbls" not in paths
    assert "/api/v1/custom-cbls/{list_id}" not in paths
    assert "/api/v1/custom-cbls/{list_id}/reader" not in paths
