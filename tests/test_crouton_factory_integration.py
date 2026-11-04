"""Regression contracts for the live Crouton Alpha OpenCode factory integration."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
selector = importlib.import_module("factory_live_opencode")


def test_crouton_installer_sets_valid_model_scoped_safety_identifier() -> None:
    """Upstream OpenCode #61497 requires a nonempty request safety identifier."""
    installer = (ROOT / ".github/scripts/install-opencode-v2.sh").read_text()
    config_text = installer.split("<<'JSON'\n", 1)[1].split("\nJSON\n", 1)[0]
    config = json.loads(config_text)

    assert config["providers"]["opencode"]["models"] == {
        "crouton-alpha-free": {
            "body": {"safety_identifier": "comic-pile-factory"},
        },
    }
    assert config["permissions"]
    assert config["policies"]


def test_crouton_runner_scopes_existing_zen_credential_and_checks_real_tool_use() -> None:
    """Do not alter anonymous DeepSeek experiments or authorize paid fallback."""
    workflow = (ROOT / ".github/workflows/free-model-factory-run.yml").read_text()
    selection = workflow.index("- name: Select execution candidate at dispatch time")
    auth = workflow.index("- name: Configure existing Zen credential for Crouton Alpha")
    smoke = workflow.index("- name: Smoke exact pinned model through OpenCode")
    assert selection < auth < smoke
    auth_step = workflow[auth:workflow.index("\n      - name:", auth + 1)]
    assert "steps.executor.outputs.source == 'opencode-free'" in auth_step
    assert "steps.executor.outputs.model == 'crouton-alpha-free'" in auth_step
    assert "secrets.OPENCODE_API_KEY || secrets.OPENCODE_ZEN_API_KEY" in auth_step
    assert "OPENCODE_API_KEY=%s" in auth_step

    smoke_step = workflow[smoke:workflow.index("\n      - name:", smoke + 1)]
    assert "opencode/crouton-alpha-free" in smoke_step
    assert "crouton-tool-smoke-marker" in smoke_step
    assert '"$(cat "$crouton_marker" 2>/dev/null || true)"' in smoke_step
    assert "grep -Eq '^(model_unavailable|provider_quota)'" in smoke_step
    assert "factory-provider-quota:v1 run=" in workflow


def test_crouton_quota_smoke_is_classified_without_permanent_retirement(tmp_path: Path) -> None:
    """A signed-off free quota failure should temporarily cool the exact model."""
    log = (
        "> build · crouton-alpha-free\n"
        "Error: Free usage limit reached. Connect a provider or subscribe to OpenCode Go."
    )
    outcome_path = tmp_path / "outcome"
    assert selector.record_smoke_failure(log, "opencode/crouton-alpha-free", outcome_path)
    assert outcome_path.read_text() == (
        "provider_quota\tOpenCode free quota exhausted for opencode/crouton-alpha-free\n"
    )
    other_path = tmp_path / "other"
    assert not selector.record_smoke_failure(log, "openrouter/stealth/crouton-alpha", other_path)
    assert not other_path.exists()

    now = int(datetime(2026, 11, 4, 17, 27, 47, tzinfo=UTC).timestamp())
    attempt = {
        "author_association": "OWNER",
        "body": (
            "<!-- factory-provider-quota:v1 run=41877651793 -->\n"
            "Source: opencode-free\n"
            "Model: crouton-alpha-free\n"
            "Attempt outcome: provider_quota\n"
            "Updated: 2026-11-04T17:27:47Z\n"
            "Run: 41877651793"
        ),
    }
    assert selector.unavailable_models([attempt], now_epoch=now) == {"crouton-alpha-free"}
    assert selector.unavailable_models(
        [attempt], now_epoch=now + selector.COOLDOWN_SECONDS
    ) == set()
