"""Focused backend coverage for the #2757 bounded guest demo adapter.

Two layers of proof for the issue's ephemerality contract:

* request-level tests prove an unauthenticated guest gets one deterministic,
  visibly-labeled sample roll, and that the demo family never leaks a bare
  ``/api/demo/*`` route;
* a static guard proves the adapter cannot reach persistence at all, so a later
  edit cannot quietly reintroduce demo writes to a real account.
"""

import ast
from pathlib import Path

from fastapi.testclient import TestClient

DEMO_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "api" / "demo.py"
DEMO_ROLL_PATH = "/api/v1/demo/roll"

# Import targets the demo adapter must never reach. The guest demo serves
# fabricated fixtures, so touching the database layer would make real
# library/queue/rating rows reachable from an unauthenticated request.
FORBIDDEN_DEMO_IMPORTS = frozenset(
    {
        "app.database",
        "app.models",
        "app.repositories",
        "app.services",
        "sqlalchemy",
    }
)


def _demo_client() -> TestClient:
    """Build a synchronous client for the default application.

    ``TestClient`` is used without its context manager so the app lifespan
    never runs: these tests exercise routing and payload shape only and must
    not require a database.

    Returns:
        Client bound to the default application instance.
    """
    from app.main import app

    return TestClient(app)


def test_demo_roll_is_public_and_deterministic() -> None:
    """An unauthenticated guest gets one reproducible seeded sample roll."""
    client = _demo_client()

    first = client.get(DEMO_ROLL_PATH)
    second = client.get(DEMO_ROLL_PATH)

    assert first.status_code == 200
    assert second.status_code == 200
    # The seed is fixed, so every visitor sees the same roll.
    assert first.json() == second.json()


def test_demo_roll_is_visibly_labeled_sample_data() -> None:
    """The served roll identifies itself as sample data, not a real library."""
    payload = _demo_client().get(DEMO_ROLL_PATH).json()

    assert "Demo" in payload["title"]
    assert payload["explanation"] is not None
    assert "Demo" in payload["explanation"]


def test_demo_roll_payload_carries_no_identity_or_session_state() -> None:
    """The demo roll exposes no account, session, or user linkage to persist."""
    payload = _demo_client().get(DEMO_ROLL_PATH).json()

    forbidden_keys = {"user_id", "session_id", "account_id"}
    assert forbidden_keys.isdisjoint(payload.keys())


def test_demo_family_exposes_no_bare_api_route() -> None:
    """The demo family is versioned-only, per the docs/API.md convention.

    ``/api/{path:path}`` answers unknown API paths with a JSON 404, so the
    retired bare prefix is observable without importing routing internals.
    """
    client = _demo_client()

    assert client.get(DEMO_ROLL_PATH).status_code == 200
    assert client.get("/api/demo/roll").status_code == 404
    assert client.get("/api/demo/bootstrap").status_code == 404


def test_demo_adapter_never_reaches_persistence() -> None:
    """Static guard: the demo adapter cannot import database machinery."""
    tree = ast.parse(DEMO_MODULE_PATH.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    assert imported.isdisjoint(FORBIDDEN_DEMO_IMPORTS)
