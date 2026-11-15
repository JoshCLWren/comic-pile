"""No claims or Actions jobs for unconfigured but still registered models."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("factory_dispatch_credential_filter", ROOT / ".github/scripts/factory_dispatch_credential_filter.py")
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def test_missing_key_blocks_all_three_vercel_lanes_without_changing_roster():
    roster = gate.roster_sources()
    assert [roster[str(n)] for n in (139, 140, 141)] == ["vercel-ai-gateway"] * 3
    kept, deferred = gate.filter_workers(["139", "140", "141", "41"], {**roster, "41": "kilo-auto"}, {})
    assert kept == ["41"] and len(deferred) == 3


def test_credential_appearing_reenables_all_lanes():
    roster = gate.roster_sources()
    workers = ["139", "140", "141"]
    assert gate.filter_workers(workers, roster, {"FACTORY_HAS_AI_GATEWAY_API_KEY": "true"}) == (workers, [])


def test_cloudflare_needs_token_and_account_and_unknown_source_fails_closed():
    roster = {"119": "cloudflare-workers-ai", "999": "unknown"}
    env = {"FACTORY_HAS_CLOUDFLARE_API_TOKEN": "true"}
    assert gate.filter_workers(["119", "999"], roster, env)[0] == []
    env["FACTORY_HAS_CLOUDFLARE_ACCOUNT_ID"] = "true"
    assert gate.filter_workers(["119", "999"], roster, env)[0] == ["119"]


def test_both_lease_writers_guard_before_assign():
    for name in ("fixed-model-factory-dispatch.yml", "fixed-model-factory-capacity-refill.yml"):
        source = (ROOT / ".github/workflows" / name).read_text()
        assert "FACTORY_HAS_AI_GATEWAY_API_KEY" in source
        assert "factory_dispatch_credential_filter.py filter" in source
        if "capacity-refill" in name:
            assert source.index("factory_dispatch_credential_filter.py filter") < source.index('assign --worker "$worker"')
            assert "factory_state_operations.py filter" in source
        else:
            assert source.index("factory_dispatch_credential_filter.py filter") < source.index('dispatch_assigned_worker "$worker"')
