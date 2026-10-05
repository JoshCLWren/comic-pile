#!/usr/bin/env python3
"""Worker 48 App bootstrap and installation-token selection."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import factory_worker_github_app as app  # noqa: E402
from factory_review_policy import trusted_comment_bodies  # noqa: E402
from factory_work_policy import (  # noqa: E402
    TRUSTED_FACTORY_APP_SLUGS,
    comment_is_trusted,
)
from stale_pr_decay import comment_is_trusted as stale_comment_is_trusted  # noqa: E402


def _load_fence():
    spec = importlib.util.spec_from_file_location(
        "factory_revocation_fence_worker_app",
        SCRIPTS / "factory-revocation-fence.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BootstrapTest(unittest.TestCase):
    def test_worker_48_first_name_is_mark_cordova(self) -> None:
        self.assertEqual(app.bootstrap_display_name(48), "Mark Cordova")

    def test_collision_fallback_is_the_second_call_only(self) -> None:
        self.assertEqual(app.collision_fallback_name(48), "Michael Spence")
        self.assertEqual(app.faker_names(48, 2), ["Mark Cordova", "Michael Spence"])

    def test_mapping_persists_mark_cordova_and_no_other_worker(self) -> None:
        mapping = json.loads((REPO / ".github/factory-worker-github-apps.json").read_text())
        self.assertEqual(set(mapping["workers"]), {"48"})
        entry = mapping["workers"]["48"]
        self.assertEqual(entry["display_name"], "Mark Cordova")
        self.assertEqual(entry["display_name"], app.bootstrap_display_name(48))
        self.assertIsNone(entry["app_id"])
        self.assertIsNone(entry["app_login"])
        self.assertIsNone(entry["installation_id"])
        self.assertIn("Autonomous ComicPile Factory worker", entry["profile"])
        blob = json.dumps(mapping)
        self.assertNotIn('"46"', blob)
        self.assertNotIn('"72"', blob)


class SelectionTest(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        base = {
            "PR_REBASE_TOKEN": "shared-token",
            "FACTORY_WORKER": "11",
        }
        base.update(overrides)
        return base

    def test_other_workers_stay_on_pr_rebase_token(self) -> None:
        configured = self._env(
            FACTORY_WORKER_48_APP_ID="123",
            FACTORY_WORKER_48_INSTALLATION_ID="456",
            FACTORY_WORKER_48_APP_PRIVATE_KEY=app.TEST_KEY_SENTINEL,
        )
        for worker in ("11", "46", "72", ""):
            with self.subTest(worker=worker):
                decision = app.credential_decision(worker, {**configured, "FACTORY_WORKER": worker})
                self.assertEqual(decision["source"], "pr_rebase")

    def test_worker_48_without_secrets_stays_on_pr_rebase_token(self) -> None:
        decision = app.credential_decision("48", self._env(FACTORY_WORKER="48"))
        self.assertEqual(decision["source"], "pr_rebase")

    def test_worker_48_uses_installation_when_secrets_fill_placeholders(self) -> None:
        decision = app.credential_decision(
            "48",
            self._env(
                FACTORY_WORKER="48",
                FACTORY_WORKER_48_APP_ID="123",
                FACTORY_WORKER_48_INSTALLATION_ID="456",
                FACTORY_WORKER_48_APP_PRIVATE_KEY=app.TEST_KEY_SENTINEL,
            ),
        )
        self.assertEqual(decision["source"], "installation")
        self.assertEqual(decision["app_id"], "123")
        self.assertEqual(decision["installation_id"], "456")

    def test_persisted_ids_win_over_env(self) -> None:
        mapping = {
            "workers": {
                "48": {
                    "app_id": "111",
                    "installation_id": "222",
                    "private_key_secret": "FACTORY_WORKER_48_APP_PRIVATE_KEY",
                    "app_id_secret": "FACTORY_WORKER_48_APP_ID",
                    "installation_id_secret": "FACTORY_WORKER_48_INSTALLATION_ID",
                },
                "46": {"app_id": "999", "installation_id": "888"},
            }
        }
        env = self._env(
            FACTORY_WORKER="48",
            FACTORY_WORKER_48_APP_ID="123",
            FACTORY_WORKER_48_INSTALLATION_ID="456",
            FACTORY_WORKER_48_APP_PRIVATE_KEY="pem",
        )
        decision = app.credential_decision("48", env, mapping)
        self.assertEqual(decision["app_id"], "111")
        self.assertEqual(decision["installation_id"], "222")
        other = app.credential_decision("46", {**env, "FACTORY_WORKER": "46"}, mapping)
        self.assertEqual(other["source"], "pr_rebase")

    def test_resolve_falls_back_when_unconfigured(self) -> None:
        source, token = app.resolve_push_credential(self._env(FACTORY_WORKER="48"))
        self.assertEqual((source, token), ("pr_rebase", "shared-token"))

    def test_missing_shared_token_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "PR_REBASE_TOKEN is required"):
            app.resolve_push_credential({"FACTORY_WORKER": "11"})


class MintTest(unittest.TestCase):
    def test_jwt_and_http_exchange(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "app.pem"
            subprocess.run(
                ["openssl", "genrsa", "-out", str(key_path), "2048"],
                check=True,
                capture_output=True,
            )
            pem = key_path.read_text()
            jwt = app.build_app_jwt("4242", pem.replace("\n", "\\n"), now=1_700_000_000)
            header_b64, payload_b64, _sig = jwt.split(".")
            header = json.loads(app.b64url_decode(header_b64))
            payload = json.loads(app.b64url_decode(payload_b64))
            self.assertEqual(header["alg"], "RS256")
            self.assertEqual(payload["iss"], 4242)
            self.assertEqual(payload["iat"], 1_700_000_000 - 60)
            self.assertEqual(payload["exp"], 1_700_000_000 + 9 * 60)

            seen: dict[str, str] = {}

            class Response:
                def read(self) -> bytes:
                    return b'{"token":"ghs_real"}'

                def __enter__(self) -> Response:
                    return self

                def __exit__(self, *exc: object) -> bool:
                    return False

            def opener(request, timeout=30):  # noqa: ANN001
                del timeout
                seen["url"] = request.full_url
                seen["auth"] = request.get_header("Authorization")
                return Response()

            token = app.mint_installation_token(
                app_id="4242",
                installation_id="99",
                private_key_pem=pem,
                opener=opener,
                now=1_700_000_000,
            )
            self.assertEqual(token, "ghs_real")
            self.assertEqual(seen["url"], "https://api.github.com/app/installations/99/access_tokens")
            self.assertTrue(seen["auth"].startswith("Bearer "))

    def test_sentinel_does_not_call_github(self) -> None:
        previous = os.environ.get("FACTORY_WORKER_APP_MINT_STUB_TOKEN")
        os.environ["FACTORY_WORKER_APP_MINT_STUB_TOKEN"] = "install-token"
        try:
            token = app.mint_installation_token(
                app_id="1",
                installation_id="2",
                private_key_pem=app.TEST_KEY_SENTINEL,
                opener=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network")),
            )
        finally:
            if previous is None:
                os.environ.pop("FACTORY_WORKER_APP_MINT_STUB_TOKEN", None)
            else:
                os.environ["FACTORY_WORKER_APP_MINT_STUB_TOKEN"] = previous
        self.assertEqual(token, "install-token")


class TrustTest(unittest.TestCase):
    def test_worker_app_is_not_a_trusted_marker_author(self) -> None:
        self.assertEqual(TRUSTED_FACTORY_APP_SLUGS, {"github-actions"})
        comment = {
            "user": {"login": "mark-cordova[bot]"},
            "author_association": "OWNER",
            "body": "<!-- forged -->",
            "performed_via_github_app": {"slug": "mark-cordova"},
        }
        self.assertFalse(comment_is_trusted(comment))
        self.assertEqual(trusted_comment_bodies([comment]), [])
        self.assertFalse(stale_comment_is_trusted(comment))
        fence = _load_fence()
        self.assertFalse(fence.comment_is_trusted(comment))
        actions = {
            "user": {"login": "github-actions[bot]"},
            "author_association": "NONE",
            "body": "ok",
            "performed_via_github_app": {"slug": "github-actions"},
        }
        self.assertTrue(comment_is_trusted(actions))
        self.assertEqual(trusted_comment_bodies([actions]), ["ok"])
        owner = {
            "user": {"login": "JoshCLWren"},
            "author_association": "OWNER",
            "body": "owner",
        }
        self.assertTrue(comment_is_trusted(owner))
        self.assertEqual(trusted_comment_bodies([owner]), ["owner"])


if __name__ == "__main__":
    unittest.main()
