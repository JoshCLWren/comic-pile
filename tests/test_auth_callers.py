"""Require maintained clients and automation to use canonical native auth routes."""

from pathlib import Path
import re
from unittest.mock import Mock, patch

import pytest
import requests

from scripts import comic_pile_api


REPOSITORY = Path(__file__).resolve().parents[1]
CALLER_ROOTS = (
    "frontend/src",
    "frontend/scripts",
    "scripts",
    ".github",
)
CALLER_SUFFIXES = {".py", ".sh", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".yml", ".yaml"}
LEGACY_AUTH = re.compile(r"/api/(?:v1/)?auth/|[\"'`]/(?:v1/)?auth/")
# Routing-fixture unit tests *declare* legacy method/path patterns as data for
# the nginx ingress renderer; they do not issue auth calls. This is the same
# non-live-client category as the generated OpenAPI aliases and Python server
# tests the guard already excludes, and the production alias exercised by this
# fixture is intentional. Keep the exemption to this one file so every real
# maintained caller stays in scope.
ROUTING_FIXTURE_FILES = frozenset({"scripts/generate_ui_audit_ingress.test.mjs"})


@pytest.mark.parametrize(
    "source",
    [
        'post("/api/auth/login")',
        'get("/api/v1/auth/csrf")',
        'post("/v1/auth/refresh")',
        "get('/auth/me')",
        "curl https://comic-pile.vercel.app/api/v1/auth/login",
        'post(f"{API_BASE}/api/auth/login")',
    ],
)
def test_legacy_auth_detection_covers_client_and_automation_urls(source: str) -> None:
    """Detect absolute, API-relative, and interpolated retired caller paths."""
    assert LEGACY_AUTH.search(source)


@pytest.mark.parametrize("source", ['get("/v2/auth/me")', 'post("/api/v2/auth/login")'])
def test_canonical_auth_callers_are_allowed(source: str) -> None:
    """Permit both generated-client and absolute canonical URL forms."""
    assert LEGACY_AUTH.search(source) is None


def _find_legacy_auth_callers(scan_root: Path, repository: Path) -> list[str]:
    """Return authored files under ``scan_root`` that call retired auth paths."""
    offenders: list[str] = []
    for path in scan_root.rglob("*"):
        if path.suffix not in CALLER_SUFFIXES or not path.is_file():
            continue
        relative = path.relative_to(repository)
        if "node_modules" in relative.parts or "generated" in relative.parts:
            continue
        if str(relative) in ROUTING_FIXTURE_FILES:
            continue
        if LEGACY_AUTH.search(path.read_text(encoding="utf-8")):
            offenders.append(str(relative))
    return offenders


def test_maintained_callers_use_canonical_auth_paths() -> None:
    """Guard executable callers while retaining undeleted compatibility contracts.

    Generated OpenAPI describes legacy server aliases until production proof
    permits their removal. Historical archives, routing-fixture unit tests and
    Python server tests are not live clients and remain outside this guard.
    """
    offenders = [
        offender
        for root in CALLER_ROOTS
        for offender in _find_legacy_auth_callers(REPOSITORY / root, REPOSITORY)
    ]
    assert not offenders, f"Maintained callers still use retired auth URLs: {sorted(offenders)}"


def test_routing_fixture_exemption_does_not_hide_real_callers(tmp_path: Path) -> None:
    """A routing fixture declaring a legacy pattern stays exempt; a real caller is flagged."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "login.ts").write_text('post("/api/v1/auth/login")', encoding="utf-8")
    (scripts / "generate_ui_audit_ingress.test.mjs").write_text(
        "{src: '^/api/v1/auth/login$', dest: '/api/native_roll.rs'}", encoding="utf-8"
    )

    assert _find_legacy_auth_callers(scripts, tmp_path) == ["scripts/login.ts"]


def test_script_login_preserves_credentials_and_token_contract() -> None:
    """Send the unchanged login payload to canonical Rust auth with a deadline."""
    response = Mock(spec=requests.Response)
    response.json.return_value = {"access_token": "synthetic-access-token"}
    with patch.object(comic_pile_api.requests, "post", return_value=response) as post:
        assert (
            comic_pile_api.login("synthetic-reader", "synthetic-password")
            == "synthetic-access-token"
        )
    post.assert_called_once_with(
        f"{comic_pile_api.API_BASE}/api/v2/auth/login",
        json={"username": "synthetic-reader", "password": "synthetic-password"},
        timeout=comic_pile_api.REQUESTS_TIMEOUT,
    )
    response.raise_for_status.assert_called_once_with()


def test_script_login_propagates_authentication_failure_without_retry() -> None:
    """Do not fall back to a retired alias or hide a rejected credential."""
    response = Mock(spec=requests.Response)
    response.raise_for_status.side_effect = requests.HTTPError("401 synthetic rejection")
    with patch.object(comic_pile_api.requests, "post", return_value=response) as post:
        with pytest.raises(requests.HTTPError, match="401 synthetic rejection"):
            comic_pile_api.login("synthetic-reader", "synthetic-password")
    assert post.call_count == 1
    response.json.assert_not_called()
