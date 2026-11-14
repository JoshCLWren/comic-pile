"""Focused contract tests for Neon factory operational state.

No external connections. Production Neon evidence is verified separately.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
spec = importlib.util.spec_from_file_location("factory_state_operations", ROOT / ".github/scripts/factory_state_operations.py")
assert spec is not None and spec.loader is not None
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)

REPO = "JoshCLWren/comic-pile"


class FakeConnection:
    def __init__(self, *, models=(), budgets=(), reservations=(), events=(), retries=(), metrics=()):
        self.models = models
        self.budgets = budgets
        self.reservations = reservations
        self.events = events
        self.retries = retries
        self.metrics = metrics

    async def fetch(self, statement, *args):
        if "FROM public.factory_model_health" in statement:
            return self.models
        if "FROM public.factory_provider_budget" in statement:
            return self.budgets
        if "FROM public.factory_provider_reservation" in statement:
            return self.reservations
        if "FROM public.factory_state_events" in statement:
            return self.events
        if "FROM public.factory_pr_stage_retry" in statement:
            return self.retries
        if "FROM public.factory_worker_metrics" in statement:
            return self.metrics
        raise AssertionError(statement)


def run(awaitable):
    return asyncio.run(awaitable)


def test_schema_contains_all_separate_operational_relations():
    ddl = "\n".join(operations.SCHEMA)
    for relation in (
        "factory_model_health", "factory_provider_budget",
        "factory_provider_reservation", "factory_pr_stage_retry",
        "factory_check_projection", "factory_worker_metrics",
        "factory_runtime_event_keys", "factory_reconciliation_cursor",
    ):
        assert relation in ddl
    assert all("DROP TABLE" not in statement for statement in operations.SCHEMA)


def test_missing_model_is_suppressed_but_unrelated_provider_is_available():
    future = datetime.now(UTC) + timedelta(minutes=20)
    db = FakeConnection(models=[{
        "source": "nvidia", "model": "nvidia/expired",
        "status": "unavailable", "cooldown_until": future,
    }])
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/expired"),
        "42": ("opencode-free", "oc/big-pickle"),
    }):
        kept, denied = run(operations._eligibility(db, REPO, ["41", "42"]))
    assert kept == ["42"]
    assert "model" in denied[0]


def test_expired_model_cooldown_is_eligible_for_a_new_probe():
    past = datetime.now(UTC) - timedelta(minutes=1)
    db = FakeConnection(models=[{
        "source": "nvidia", "model": "nvidia/expired",
        "status": "unavailable", "cooldown_until": past,
    }])
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/expired"),
    }):
        kept, denied = run(operations._eligibility(db, REPO, ["41"]))
    assert kept == ["41"]
    assert not denied


def test_provider_cooldown_affects_its_account_not_every_source():
    future = datetime.now(UTC) + timedelta(minutes=20)
    db = FakeConnection(budgets=[{
        "source": "nvidia", "cooldown_until": future,
        "concurrency_limit": None, "daily_limit": None,
        "usage_day": datetime.now(UTC).date(), "daily_used": 0,
    }])
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/a"),
        "42": ("nvidia", "nvidia/b"),
        "43": ("opencode-free", "oc/big-pickle"),
    }):
        kept, denied = run(operations._eligibility(db, REPO, ["41", "42", "43"]))
    assert kept == ["43"]
    assert len(denied) == 2


def test_provider_concurrency_limit_does_not_invent_unconfigured_caps():
    db = FakeConnection(
        budgets=[{
            "source": "nvidia", "cooldown_until": None,
            "concurrency_limit": 1, "daily_limit": None,
            "usage_day": datetime.now(UTC).date(), "daily_used": 0,
        }],
        reservations=[{"source": "nvidia", "n": 1}],
    )
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/a"),
        "43": ("opencode-free", "oc/big-pickle"),
    }):
        kept, denied = run(operations._eligibility(db, REPO, ["41", "43"]))
    assert kept == ["43"]
    assert "full" in denied[0]


def test_daily_usage_reads_neon_assignments_not_github_history():
    db = FakeConnection(events=[
        {"worker": "41", "source": None},
        {"worker": "42", "source": "opencode-free"},
        {"worker": "41", "source": "nvidia"}
    ])
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/a"),
        "42": ("opencode-free", "oc/big-pickle"),
    }):
        usage = run(operations._daily_usage(db, REPO, ["nvidia", "opencode-free", "mistral"]))
    assert usage == {"nvidia": 2, "opencode-free": 1, "mistral": 0}


def test_retry_suppression_is_exact_head_and_exact_stage_only():
    sha = "a" * 40
    db = FakeConnection(retries=[{
        "pr_number": 5000, "head_sha": sha,
        "stage": "factory:review",
    }])
    assert run(operations._cooling_prs(db, REPO, {5000: (sha, "factory:review")})) == {5000}
    assert run(operations._cooling_prs(db, REPO, {5000: ("b" * 40, "factory:review")})) == set()
    assert run(operations._cooling_prs(db, REPO, {5000: (sha, "factory:ci")})) == set()


def test_worker_ranking_preserves_source_diversity():
    db = FakeConnection(metrics=[
        {"worker": "41", "attempts": 10, "productive": 1},
        {"worker": "42", "attempts": 10, "productive": 7},
    ])
    with patch.object(operations, "_roster", return_value={
        "41": ("nvidia", "nvidia/a"),
        "42": ("nvidia", "nvidia/b"),
        "43": ("opencode-free", "oc/big-pickle"),
    }):
        ranked = run(operations._rank_workers(db, REPO, ["41", "43", "42"]))
    assert ranked == ["42", "43", "41"]


def test_model_scoped_provider_route_never_cools_unrelated_routes():
    assert "omniroute-free" in operations.MODEL_SCOPED_SOURCES
    assert "nvidia" not in operations.MODEL_SCOPED_SOURCES
    assert operations.MODEL_COOLDOWNS["model_unavailable"] == 21600


def test_exact_head_checks_are_advisory_not_merge_authorization():
    workflow = (ROOT / ".github/workflows/factory-check-projection.yml").read_text()
    assert "factory_state_operations.py ingest-check" in workflow
    assert "pull_request_target:" not in workflow
    assert "gh pr merge" not in workflow
