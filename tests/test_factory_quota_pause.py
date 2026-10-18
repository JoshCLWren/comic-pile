"""Tests for durable provider-quota pauses of fixed-model workers."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, UTC
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "factory_quota_pause", SCRIPTS / "factory_quota_pause.py"
)
assert _SPEC and _SPEC.loader
qp = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = qp
_SPEC.loader.exec_module(qp)

BEFORE_RESET = datetime(2026, 10, 18, 13, 0, tzinfo=UTC)
AFTER_RESET = datetime(2026, 11, 1, 0, 0, 1, tzinfo=UTC)


def _write(tmp_path: Path, pauses: list[dict[str, object]]) -> Path:
    path = tmp_path / "pauses.json"
    path.write_text(json.dumps({"schema_version": 1, "pauses": pauses}), encoding="utf-8")
    return path


def test_repo_config_pauses_w48_and_w55_until_november() -> None:
    """The committed config quota-pauses Mistral w48 and Ollama w55 until ~Nov 1."""
    active = qp.active_pauses(BEFORE_RESET)
    assert set(active) == {48, 55}
    for worker in (48, 55):
        assert active[worker].paused_until == datetime(2026, 11, 1, tzinfo=UTC)
        assert "provider_quota" in active[worker].reason
    assert qp.active_pauses(AFTER_RESET) == {}


def test_paused_workers_remain_on_roster_and_expected_workers() -> None:
    """Quota pause is not retirement: w48/w55 stay in the TSV and expected list."""
    tsv = (ROOT / ".github" / "free-model-factories.tsv").read_text(encoding="utf-8")
    rostered = {
        line.split("\t")[0] for line in tsv.splitlines() if line and not line.startswith("#")
    }
    expected = json.loads((ROOT / ".github" / "factory-expected-workers.json").read_text())
    for worker in (48, 55):
        assert str(worker) in rostered
        assert worker in expected["expected_workers"]


def test_filter_preserves_order_and_logs_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Filtering drops only active pauses and reports why."""
    kept, messages = qp.filter_workers(["21", "48", "46", "55", "60"], now=BEFORE_RESET)
    assert kept == ["21", "46", "60"]
    assert any(
        m.startswith("Factory 48 paused until 2026-11-01T00:00:00Z (config)") for m in messages
    )
    kept, messages = qp.filter_workers(["48", "55"], now=AFTER_RESET)
    assert kept == ["48", "55"] and messages == []


def test_worker_46_can_never_be_paused(tmp_path: Path) -> None:
    """Worker 46 is protected from quota-pause logic."""
    path = _write(
        tmp_path,
        [
            {
                "worker": 46,
                "paused_until": "2026-11-01T00:00:00Z",
                "reason": "x",
                "reset_source": "config",
            }
        ],
    )
    with pytest.raises(ValueError, match="protected"):
        qp.load_pauses(path)


def test_rejects_non_utc_and_duplicates(tmp_path: Path) -> None:
    """Timestamps must be explicit UTC and workers unique."""
    with pytest.raises(ValueError):
        qp.load_pauses(_write(tmp_path, [{"worker": 48, "paused_until": "2026-11-01"}]))
    dup = {"worker": 48, "paused_until": "2026-11-01T00:00:00Z"}
    with pytest.raises(ValueError, match="duplicate"):
        qp.load_pauses(_write(tmp_path, [dup, dup]))


def test_is_paused_handles_non_numeric_ids() -> None:
    """Non-numeric worker ids are never paused."""
    assert qp.is_paused("local") is None
    assert qp.is_paused(None) is None
    assert qp.is_paused("48", now=BEFORE_RESET) is not None


def test_pause_module_parses_on_older_python() -> None:
    """The dispatcher's system python3 may predate 3.14 syntax relaxations."""
    import ast

    source = (SCRIPTS / "factory_quota_pause.py").read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 10))


def test_missing_file_means_no_pauses(tmp_path: Path) -> None:
    """A missing pause file disables pausing rather than failing dispatch."""
    assert qp.load_pauses(tmp_path / "absent.json") == []


def test_cli_filter(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The dispatcher CLI emits a compact JSON array on stdout."""
    import io

    monkeypatch.setattr(
        qp,
        "active_pauses",
        lambda now=None, pauses=None: {
            48: qp.QuotaPause(48, "mistral", datetime(2026, 11, 1, tzinfo=UTC), "q", "config")
        },
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO('["48","21"]'))
    assert qp.main(["filter"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == '["21"]'
    assert "Factory 48 paused until" in out.err


def test_classifier_labels_quota_exhaustion() -> None:
    """Quota exhaustion classifies as provider_quota rather than unknown_failure."""
    spec = importlib.util.spec_from_file_location(
        "classify_fixed", SCRIPTS / "classify-fixed-model-run.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    lock = (
        "Factory 48 locked: source=mistral model=codestral-latest runtime=mistral/codestral-latest "
        "minute=:50 scheduler=dispatcher configured=true\n"
    )
    result = module.classify(
        lock + "Smoke exact pinned model through OpenCode\nError: API budget exhausted.\n"
    )
    assert result.outcome_class == "provider_quota"
    assert "provider_quota" in module.CANONICAL_OUTCOME_CLASSES


def test_work_controller_assign_skips_paused_worker() -> None:
    """The controller refuses to lease work to a quota-paused worker."""
    source = (SCRIPTS / "factory-work-controller.py").read_text(encoding="utf-8")
    assign_body = source.split("def assign(", 1)[1].split("\ndef ", 1)[0]
    assert assign_body.index("quota_pause_for(worker)") < assign_body.index(
        "worker_has_active_lease(worker)"
    )


def test_dispatch_workflows_filter_paused_workers() -> None:
    """Dispatcher and refill filter paused workers before capacity truncation."""
    for name in ("fixed-model-factory-dispatch.yml", "fixed-model-factory-capacity-refill.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert text.index("factory_quota_pause.py filter") < text.index('controller" capacity')


def test_scheduled_batch_filters_pauses_before_offer_cap() -> None:
    """Paused lanes must not displace eligible workers inside the offer cap."""
    text = (ROOT / ".github/workflows/fixed-model-factory-dispatch.yml").read_text(encoding="utf-8")
    scheduled = text[text.index("source_seed=") : text.index("Scheduled batch:")]
    assert 'head -n "$offer_count"' not in scheduled
    assert scheduled.index("factory_quota_pause.py filter") < scheduled.index(".[:$cap]")
