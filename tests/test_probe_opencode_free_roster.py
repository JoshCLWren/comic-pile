"""Regression coverage for the OpenCode free-roster OmniRoute probe."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "scripts"
    / "probe_opencode_free_roster.py"
)


def load_module() -> ModuleType:
    """Load the probe script without packaging .github."""
    spec = importlib.util.spec_from_file_location("probe_opencode_free_roster", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROBE = load_module()


def test_free_roster_filter_keeps_opencode_and_zen_models() -> None:
    """Factory and catalog ids stay first-class across oc / opencode / zen."""
    assert PROBE.is_free_roster_model("oc/nemotron-3.5-lightning-free")
    assert PROBE.is_free_roster_model("opencode/deepseek-v4-flash-free")
    assert PROBE.is_free_roster_model("opencode-zen/muse-spark-1.2")
    assert PROBE.is_free_roster_model("big-pickle")
    assert PROBE.is_free_roster_model("muse-spark-1.2-contributor-free")
    assert not PROBE.is_free_roster_model("nvidia/nemotron-3-ultra-550b-a55b")
    assert not PROBE.is_free_roster_model("openrouter/stealth/ox-alpha")
    assert not PROBE.is_free_roster_model("oc/paid-frontier")


def test_classify_probe_buckets_match_operator_instrument() -> None:
    """Map the live OmniRoute statuses Josh already hand-probes."""
    assert PROBE.classify_probe_response(status_code=200, cost="0.0000000000") == (
        "ok",
        "200, $0",
    )
    assert PROBE.classify_probe_response(status_code=429, body="Too Many Requests")[0] == (
        "rate_limited"
    )
    assert PROBE.classify_probe_response(
        status_code=401, body='{"error":"model is not supported"}'
    )[0] == "unsupported"
    assert PROBE.classify_probe_response(
        status_code=400,
        body="Model is not available in the active live catalog",
    )[0] == "catalog_miss"
    assert PROBE.classify_probe_response(status_code=402, body="wants API key")[0] == (
        "auth_paid"
    )
    assert PROBE.classify_probe_response(status_code=None, timed_out=True) == (
        "timeout",
        "probe timed out",
    )
    assert PROBE.classify_probe_response(status_code=500, body="upstream exploded")[0] == (
        "error"
    )
    assert PROBE.classify_probe_response(status_code=200, cost="0.12")[0] == "auth_paid"


def test_build_probe_ids_covers_both_live_connections() -> None:
    """Expand factory names onto oc and zen without dropping catalog extras."""
    ids = PROBE.build_probe_ids(
        ["big-pickle", "nemotron-3.5-lightning-free"],
        ["oc/north-mini-code-free", "opencode-zen/muse-spark-1.2"],
    )

    assert "oc/big-pickle" in ids
    assert "opencode-zen/big-pickle" in ids
    assert "oc/nemotron-3.5-lightning-free" in ids
    assert "opencode-zen/nemotron-3.5-lightning-free" in ids
    assert "oc/north-mini-code-free" in ids
    assert "opencode-zen/muse-spark-1.2" in ids


def test_collect_roster_is_stale_without_credentials(tmp_path: Path) -> None:
    """Missing OmniRoute config still renders unknown/stale rows."""
    manifest = tmp_path / "free-model-factories.tsv"
    manifest.write_text(
        "39\topencode-free\tbig-pickle\t5\tdispatcher\tOpenCode Big Pickle\n",
        encoding="utf-8",
    )

    snapshot = PROBE.collect_roster(env={}, manifest_path=manifest, now="2026-09-05T20:00:00Z")

    assert snapshot.freshness == "stale"
    assert snapshot.checked_at == "2026-09-05T20:00:00Z"
    assert snapshot.models[0].model_id == "oc/big-pickle"
    assert snapshot.models[0].status == "unknown"
    assert "unknown/stale" in snapshot.detail
    assert "zen is off" not in snapshot.detail.lower()
    assert any(item.provider == "opencode-zen" for item in snapshot.connections)


def test_collect_roster_classifies_live_http_and_keeps_zen_first_class(
    tmp_path: Path,
) -> None:
    """A live gateway probe fills status buckets without disabling Zen."""
    manifest = tmp_path / "free-model-factories.tsv"
    manifest.write_text(
        "\n".join(
            [
                "45\topencode-free\tnemotron-3.5-lightning-free\t35\tdispatcher\tLightning",
                "39\topencode-free\tbig-pickle\t5\tdispatcher\tPickle",
                "43\topencode-free\tlaguna-s-2.1-free\t25\tdispatcher\tLaguna",
                "47\topencode-free\tmuse-spark-1.2-contributor-free\t45\tdispatcher\tMuse",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_http(
        method: str,
        url: str,
        *,
        token: str,
        payload: dict[str, object] | None = None,
        timeout: float = 12.0,
    ) -> object:
        del token, timeout
        if url.endswith("/api/providers"):
            return PROBE.HttpResult(
                status_code=200,
                body=json.dumps(
                    {
                        "connections": [
                            {
                                "provider": "opencode",
                                "isActive": True,
                                "testStatus": "active",
                            },
                            {
                                "provider": "opencode-zen",
                                "isActive": True,
                                "testStatus": "active",
                            },
                        ]
                    }
                ),
            )
        if url.endswith("/api/v1/models"):
            return PROBE.HttpResult(
                status_code=200,
                body=json.dumps(
                    {
                        "data": [
                            {"id": "oc/nemotron-3.5-lightning-free"},
                            {"id": "opencode-zen/nemotron-3.5-lightning-free"},
                            {"id": "oc/north-mini-code-free"},
                        ]
                    }
                ),
            )
        if method == "POST" and payload:
            model = str(payload.get("model") or "")
            if "lightning" in model:
                return PROBE.HttpResult(
                    status_code=200,
                    body='{"choices":[{"message":{"content":"OPENCODE_FREE_ROSTER_OK"}}]}',
                    headers={"x-omniroute-response-cost": "0.0000000000"},
                )
            if model.endswith("big-pickle"):
                return PROBE.HttpResult(status_code=429, body="Too Many Requests / cooling")
            if "laguna" in model:
                return PROBE.HttpResult(status_code=401, body="not supported")
            if "muse-spark" in model or "north-mini" in model:
                return PROBE.HttpResult(
                    status_code=400,
                    body="not available in the active live catalog",
                )
            return PROBE.HttpResult(status_code=500, body="boom")
        return PROBE.HttpResult(status_code=404, body="missing")

    snapshot = PROBE.collect_roster(
        env={
            "OMNIROUTE_BASE_URL": "https://omniroute.example/v1",
            "OMNIROUTE_API_KEY": "lane-key",
            "OMNIROUTE_MANAGEMENT_API_KEY": "mgmt-key",
        },
        manifest_path=manifest,
        http=fake_http,
        now="2026-09-05T20:10:00Z",
    )

    by_id = {row.model_id: row for row in snapshot.models}
    assert snapshot.freshness == "live"
    assert snapshot.checked_at == "2026-09-05T20:10:00Z"
    assert by_id["oc/nemotron-3.5-lightning-free"].status == "ok"
    assert by_id["opencode-zen/nemotron-3.5-lightning-free"].status == "ok"
    assert by_id["oc/big-pickle"].status == "rate_limited"
    assert by_id["oc/laguna-s-2.1-free"].status == "unsupported"
    assert by_id["oc/muse-spark-1.2-contributor-free"].status == "catalog_miss"
    assert by_id["oc/north-mini-code-free"].status == "catalog_miss"
    assert {item.provider: item.active for item in snapshot.connections} == {
        "opencode": True,
        "opencode-zen": True,
    }
    assert "providerOverride" in snapshot.detail
    assert "zen is off" not in snapshot.detail.lower()


def test_collect_roster_survives_gateway_errors(tmp_path: Path) -> None:
    """A dead management API still yields a renderable stale table."""
    manifest = tmp_path / "free-model-factories.tsv"
    manifest.write_text(
        "40\topencode-free\tdeepseek-v4-flash-free\t10\tdispatcher\tDeepSeek\n",
        encoding="utf-8",
    )

    def exploding_http(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("connection refused")

    snapshot = PROBE.collect_roster(
        env={
            "OMNIROUTE_BASE_URL": "https://omniroute.example",
            "OMNIROUTE_API_KEY": "lane-key",
        },
        manifest_path=manifest,
        http=exploding_http,
        now="2026-09-05T20:20:00Z",
    )

    assert snapshot.freshness == "stale"
    assert snapshot.models
    assert all(row.status == "unknown" for row in snapshot.models)
    assert snapshot.checked_at == "2026-09-05T20:20:00Z"
