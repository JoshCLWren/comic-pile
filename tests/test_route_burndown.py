"""Regression tests for the deterministic v2 route burndown generator.

The generator in ``scripts/generate_route_burndown.py`` derives one checked-in
inventory (``docs/api/v2-route-inventory.json``) and one compact generated
``AGENTS.md`` runtime section from deployed ingress in ``vercel.json``. These
tests pin the current burndown (41 live operations: 40 Native Rust + the one
transitional Python operation) and the ``--check`` determinism contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.generate_route_burndown import (
    BurndownGenerationError,
    _classify_burndown,
    _load_routes,
    _render_agents_block,
    _render_agents_text,
    _render_inventory,
    load_json,
)


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "docs" / "api" / "v2-route-inventory.json"
VERCEL_PATH = ROOT / "vercel.json"
AGENTS_PATH = ROOT / "AGENTS.md"


def _operation(
    operations: list[dict[str, object]], method: str, path: str
) -> dict[str, object]:
    """Find one inventory operation by method and path.

    Args:
        operations: Inventory operation dicts.
        method: HTTP method.
        path: Path template.

    Returns:
        The matching operation dict.

    Raises:
        AssertionError: When no operation matches.
    """
    for operation in operations:
        if operation.get("method") == method and operation.get("path") == path:
            return operation
    raise AssertionError(f"missing operation {method} {path}")


def test_burndown_summary_matches_deployed_ingress() -> None:
    """Inventory burndown reports 40 Native Rust + one Python operation."""
    inventory = load_json(INVENTORY_PATH)
    burndown = inventory.get("burndown")
    assert isinstance(burndown, dict)
    assert burndown.get("total_live_operations") == 41
    assert burndown.get("native_rust") == 40
    assert burndown.get("python_fastapi") == 1
    assert burndown.get("native_rust_status") == 40
    assert burndown.get("unreferenced_or_orphaned") == 1
    assert burndown.get("ingress_source") == "vercel.json"
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    assert len(operations) == 41
    for operation in operations:
        assert operation.get("ingress_destination")
        assert operation.get("burndown_status")
        assert operation.get("verified_against") == "vercel.json"


def test_reading_boundaries_split_uses_deployed_ingress() -> None:
    """POST boundaries is Native Rust; GET detail is Python transitional."""
    inventory = load_json(INVENTORY_PATH)
    raw_operations = inventory.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    post = _operation(operations, "POST", "/api/v2/reading-boundaries")
    assert post.get("runtime") == "native-rust"
    assert post.get("ingress_destination") == "/api/native_roll.rs"
    assert post.get("burndown_status") == "native Rust"
    get_detail = _operation(operations, "GET", "/api/v2/reading-boundaries/{thread_id}")
    assert get_detail.get("runtime") == "python-fastapi"
    assert get_detail.get("ingress_destination") == "/api/index.py"
    assert get_detail.get("burndown_status") == "unreferenced/orphaned"
    assert get_detail.get("owning_issue") == 4335


def test_classify_distinguishes_all_burndown_statuses() -> None:
    """Each issue status has a distinct classification rule."""
    assert _classify_burndown("native-rust", [], "/api/native_roll.rs") == "native Rust"
    assert (
        _classify_burndown("native-rust", ["x"], "/api/native_issue.rs")
        == "native Rust"
    )
    assert (
        _classify_burndown("python-fastapi", [], "/api/native_roll.rs")
        == "shadowed by Rust"
    )
    assert (
        _classify_burndown("python-fastapi", ["caller.ts"], "/api/index.py")
        == "live transitional Python with callers"
    )
    assert (
        _classify_burndown("python-fastapi", [], "/api/index.py")
        == "unreferenced/orphaned"
    )


def test_native_declaration_contradicting_ingress_fails() -> None:
    """A native declaration that ingresses to Python is a hard error."""
    with pytest.raises(BurndownGenerationError):
        _classify_burndown("native-rust", [], "/api/index.py")


def test_rendered_outputs_match_checked_in_files() -> None:
    """Re-rendered inventory and agents section equal the checked-in bytes."""
    inventory = load_json(INVENTORY_PATH)
    routes = _load_routes(VERCEL_PATH)
    _, inventory_text = _render_inventory(inventory, routes)
    assert INVENTORY_PATH.read_text(encoding="utf-8") == inventory_text
    inventory_from_file = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert isinstance(inventory_from_file, dict)
    raw_operations = inventory_from_file.get("operations")
    assert isinstance(raw_operations, list)
    operations = [item for item in raw_operations if isinstance(item, dict)]
    block = _render_agents_block(operations)
    agents_original = AGENTS_PATH.read_text(encoding="utf-8")
    assert _render_agents_text(agents_original, block) == agents_original


def test_agents_table_uses_deployed_ingress_not_url_version() -> None:
    """AGENTS.md generated section reflects vercel.json destinations."""
    agents = AGENTS_PATH.read_text(encoding="utf-8")
    assert "<!-- route-burndown:begin" in agents
    assert "Live v2 operations: 41 (40 native-rust + 1 python orphan)" in agents
    assert "`/api/native_roll.rs`, `/api/native_issue.rs`" in agents
    assert (
        "Python orphan: `GET /api/v2/reading-boundaries/{thread_id} "
        "-> python-fastapi` via `/api/index.py`" in agents
    )
    assert "`POST /api/v2/reading-boundaries -> native-rust`" in agents
    assert "`GET /api/v2/reading-boundaries/{thread_id} -> python-fastapi`" in agents
    assert "see `docs/api/v2-route-inventory.json` (authoritative)" in agents
    assert "Deployed runtime by cutover owner" in agents
    assert "- #4335 (10):" in agents
    assert "- #4684 (16):" in agents
    assert agents.count("<!-- route-burndown:end -->") == 1
