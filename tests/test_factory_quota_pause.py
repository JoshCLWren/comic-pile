"""Tests for durable provider-quota pauses of fixed-model workers."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
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

BEFORE_RESET = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
AFTER_RESET = datetime(2026, 11, 1, 0, 0, 1, tzinfo=UTC)


def _write(tmp_path: Path, pauses: list[dict[str, object]]) -> Path:
    path = tmp_path / "pauses.json"
    path.write_text(json.dumps({"schema_version": 1, "pauses": pauses}), encoding="utf-8")
    return path


def test_repo_config_pauses_w48_and_w55_until_november() -> None:
    """The committed config quota-pauses Mistral w48 and Ollama w55 until ~Nov 1."""
    active = qp.active_pauses(BEFORE_RESET)
    assert set(active) == {48, 55}
    assert active[48].paused_until == datetime(2026, 11, 1, tzinfo=UTC)
    assert active[55].paused_until == datetime(2026, 10, 18, 0, 29, 5, tzinfo=UTC)
    for worker in (48, 55):
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


def test_parse_retry_after_seconds_and_http_date(tmp_path: Path) -> None:
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert qp.parse_retry_after("120", now=now) == datetime(2026, 10, 18, 12, 2, tzinfo=UTC)
    parsed = qp.parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT", now=now)
    assert parsed is not None and parsed.tzinfo is not None


def test_parse_rate_limit_reset_variants(
    now: datetime = datetime(2026, 10, 18, 12, 0, tzinfo=UTC),
) -> None:
    assert qp.parse_rate_limit_reset({"x-ratelimit-reset": "60"}, now=now) == datetime(
        2026, 10, 18, 12, 1, tzinfo=UTC
    )
    assert qp.parse_rate_limit_reset({"x-ratelimit-reset-requests": "6m0s"}, now=now) == datetime(
        2026, 10, 18, 12, 6, tzinfo=UTC
    )
    assert qp.parse_rate_limit_reset({"X-RateLimit-Reset": "1729268880"}, now=now) is not None


def test_classify_quota_failures_mistral_402_and_ollama_429() -> None:
    assert qp.classify_quota_failure(
        402,
        '{"message":"API budget exhausted.","type":"billing_api_budget_exhausted","code":"2303"}',
    )
    assert qp.classify_quota_failure(
        429, "you have reached your monthly usage limit, upgrade for higher limits"
    )
    assert not qp.classify_quota_failure(500, "Model is unavailable")
    assert not qp.classify_quota_failure(500, "Something else went wrong")


def test_parse_reset_from_body_and_ollama_balance(tmp_path: Path) -> None:
    body = '{"message":"API budget exhausted.","type":"billing_api_budget_exhausted"}'
    reset = qp.parse_reset_from_body(body)
    assert reset is not None
    balance = tmp_path / "balance.json"
    balance.write_text(
        json.dumps({"included": {"period": {"until": "2026-10-18T00:29:05Z"}}}),
        encoding="utf-8",
    )
    parsed = qp.parse_ollama_balance_reset("file://" + str(balance))
    assert parsed == datetime(2026, 10, 18, 0, 29, 5, tzinfo=UTC)
    parsed_offset = qp.parse_reset_from_body("reset at 2026-11-01T13:00:00-05:00")
    assert parsed_offset == datetime(2026, 11, 1, 18, 0, 0, tzinfo=UTC)


def test_unknown_reset_uses_backoff_not_tomorrow() -> None:
    reset = qp.parse_reset_from_config("unknown-provider")
    assert reset is None


def test_create_pause_and_resume_worker(tmp_path: Path) -> None:
    path = tmp_path / "pauses.json"
    pause = qp.create_pause(
        48,
        provider="mistral",
        model="codestral-latest",
        status_code=402,
        body='{"type":"billing_api_budget_exhausted"}',
        run_id="123",
        path=path,
    )
    assert pause.worker == 48
    assert pause.reset_source in ("body", "config", "backoff", "header", "balance")
    # Expired pause with failing smoke re-pauses
    past = datetime(2020, 1, 1, tzinfo=UTC)
    paused = qp.resume_worker(48, path=path, smoke_fn=lambda w: False, now=past)
    assert paused is False
    # With passing smoke it clears
    expired_path = tmp_path / "pauses2.json"
    qp.save_pauses(
        [qp.QuotaPause(48, "mistral", datetime(2020, 1, 1, tzinfo=UTC), "q", "config")],
        expired_path,
    )
    resumed = qp.resume_worker(
        48, path=expired_path, smoke_fn=lambda w: True, now=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert resumed is True


def test_resume_worker_no_smoke_does_not_auto_resume(tmp_path: Path) -> None:
    path = tmp_path / "pauses.json"
    qp.save_pauses(
        [qp.QuotaPause(48, "mistral", datetime(2020, 1, 1, tzinfo=UTC), "q", "config")], path
    )
    resumed = qp.resume_worker(48, path=path, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert resumed is False


def test_expired_pause_runs_exactly_one_resume_smoke(tmp_path: Path) -> None:
    """An expired pause runs one smoke per resume call; a pass clears the pause."""
    path = tmp_path / "pauses.json"
    qp.save_pauses(
        [qp.QuotaPause(48, "mistral", datetime(2020, 1, 1, tzinfo=UTC), "q", "config")], path
    )
    calls: list[int] = []

    def smoke(worker: int) -> bool:
        calls.append(worker)
        return True

    assert qp.resume_worker(48, path=path, smoke_fn=smoke, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert calls == [48]
    assert qp.load_pauses(path) == []

    # A worker without a pause is dispatchable and never runs a smoke.
    calls.clear()
    assert qp.resume_worker(21, path=path, smoke_fn=smoke, now=datetime(2026, 1, 1, tzinfo=UTC))
    assert calls == []


def test_failed_resume_repauses_with_backoff(tmp_path: Path) -> None:
    """A failed resume smoke re-pauses on the bounded backoff, keeping the reason flat."""
    path = tmp_path / "pauses.json"
    qp.save_pauses(
        [
            qp.QuotaPause(
                55,
                "ollama-cloud",
                datetime(2020, 1, 1, tzinfo=UTC),
                "provider_quota: Ollama monthly usage limit",
                "balance",
                model="nemotron-3-nano:30b",
                evidence_run="38255409735",
                attempt=1,
            )
        ],
        path,
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert qp.resume_worker(55, path=path, smoke_fn=lambda w: False, now=now) is False
    repaused = qp.load_pauses(path)[0]
    assert repaused.attempt == 2
    assert repaused.reset_source == "backoff"
    assert repaused.paused_until == qp.calculate_backoff(2, now=now)
    assert repaused.paused_until > now
    assert repaused.reason == "provider_quota: Ollama monthly usage limit"
    assert repaused.provider == "ollama-cloud"
    assert repaused.evidence_run == "38255409735"


def test_ollama_reset_falls_back_balance_then_config_then_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reset resolution order is balance, then config window, then backoff."""
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    balance_reset = datetime(2026, 10, 19, 0, 29, 5, tzinfo=UTC)
    monkeypatch.setattr(qp, "parse_ollama_balance_reset", lambda *a, **k: balance_reset)
    with_balance = qp.create_pause(
        55,
        provider="ollama-cloud",
        status_code=429,
        body="monthly usage limit",
        path=tmp_path / "a.json",
        now=now,
    )
    assert with_balance.reset_source == "balance"
    assert with_balance.paused_until == balance_reset

    monkeypatch.setattr(qp, "parse_ollama_balance_reset", lambda *a, **k: None)
    config = qp.create_pause(
        55,
        provider="ollama-cloud",
        status_code=429,
        body="monthly usage limit",
        path=tmp_path / "b.json",
        now=now,
    )
    assert config.reset_source == "config"
    assert config.paused_until == datetime(2026, 11, 1, tzinfo=UTC)

    backoff = qp.create_pause(
        21,
        provider="unknown-provider",
        status_code=500,
        body="boom",
        path=tmp_path / "c.json",
        now=now,
    )
    assert backoff.reset_source == "backoff"
    assert backoff.paused_until == now + timedelta(hours=1)


def test_backoff_is_bounded_by_the_daily_cap() -> None:
    """1h, 2h, 4h ... capped at 24h so a pause is re-checked at least daily."""
    now = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
    assert qp.calculate_backoff(0, now=now) == now + timedelta(hours=1)
    assert qp.calculate_backoff(1, now=now) == now + timedelta(hours=2)
    assert qp.calculate_backoff(2, now=now) == now + timedelta(hours=4)
    assert qp.calculate_backoff(20, now=now) == now + timedelta(hours=24)


def test_visibility_output_includes_utc_ct_and_source() -> None:
    """Factory visibility output carries the reset time in UTC and CT plus its source."""
    pause = qp.QuotaPause(
        48,
        "mistral",
        datetime(2026, 11, 1, tzinfo=UTC),
        "provider_quota: budget exhausted",
        "config",
    )
    text = qp.describe_for_visibility(pause)
    assert "Factory 48 paused until 2026-11-01T00:00:00Z UTC" in text
    assert "2026-10-31T19:00:00 CT" in text
    assert "(config)" in text


def test_worker_46_never_paused_by_create(tmp_path: Path) -> None:
    path = tmp_path / "pauses.json"
    with pytest.raises(ValueError, match="protected"):
        qp.create_pause(46, provider="mistral", path=path)
