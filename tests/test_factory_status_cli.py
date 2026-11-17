"""Read-only local factory status checks with synthetic GitHub observations."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, UTC
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "factory_status_cli", Path(__file__).resolve().parents[1] / "scripts" / "factory-status.py"
)
assert SPEC and SPEC.loader
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)
NOW = datetime(2026, 11, 17, 17, 30, tzinfo=UTC)


def run(name, state, **kwargs):
    return {
        "name": name, "status": state, "created_at": NOW.isoformat(),
        "html_url": "https://github.com/org/repo/actions/runs/1", **kwargs,
    }


def fetch_factory(entries, dispatcher, prs, ci):
    def fetch(url):
        if "free-model-factory-entry" in url:
            return {"workflow_runs": entries}
        if "fixed-model-factory-dispatch" in url:
            return {"workflow_runs": dispatcher}
        if "ci.yml" in url:
            assert "branch=main" in url
            return {"workflow_runs": ci}
        if "pulls?" in url:
            return prs
        raise AssertionError(f"Unexpected API read: {url}")
    return fetch


def test_running_workflows_do_not_prove_delivery():
    fetching = fetch_factory(
        [run("Factory worker", "in_progress")],
        [run("dispatch", "completed", conclusion="success")], [], [],
    )
    report = status.collect(fetching, "org/repo", NOW)
    assert report["verdict"] == "WORKERS RUNNING; DELIVERY NOT PROVEN"
    assert "1 running" in status.render(report)


def test_successful_worker_without_code_does_not_mean_healthy():
    fetching = fetch_factory(
        [run("Factory worker", "completed", conclusion="success")], [], [], [],
    )
    report = status.collect(fetching, "org/repo", NOW)
    assert report["verdict"] == "NO RECENT FACTORY DELIVERY PROVEN"
    assert "1 successful" in status.render(report)


def test_produced_factory_pr_is_distinguished_from_local_factory_pr():
    def pr(number, *, model=False, merged=False):
        return {
            "number": number, "labels": [{"name": "factory"}],
            "created_at": NOW.isoformat(),
            "merged_at": NOW.isoformat() if merged else None,
            "body": "Produced by fixed-model Factory 77" if model else "Local changes",
        }
    report = status.collect(
        fetch_factory([], [], [pr(1), pr(2, model=True, merged=True)], []),
        "org/repo", NOW,
    )
    assert len(report["opened"]) == 2
    assert len(report["model_merged"]) == 1
    assert report["verdict"] == "FACTORY PR MERGED (production not verified)"
    assert "local and remote contributors included" in status.render(report)


def test_dashboard_staleness_does_not_hide_active_work():
    snapshot = {
        "generated_at": (NOW - timedelta(hours=6)).isoformat(),
        "busy_workers": 1, "throughput": {"merged_hour": 3},
    }
    report = status.collect(
        fetch_factory([run("Worker", "in_progress")], [], [], []),
        "org/repo", NOW, snapshot=snapshot,
    )
    assert report["snapshot_freshness"] == "STALE"
    assert "6h 0m ago" in status.render(report)
    assert report["verdict"] == "WORKERS RUNNING; DELIVERY NOT PROVEN"


def test_api_failure_is_unknown_not_zero_workers():
    def bad(_endpoint):
        raise RuntimeError("GitHub unavailable")
    try:
        status.collect(bad, "org/repo", NOW)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Failed reads must not look like an idle healthy factory")


def test_old_factory_pr_is_not_recent_delivery():
    old = (NOW - timedelta(hours=2)).isoformat()
    pr = {
        "number": 1, "labels": [{"name": "factory"}],
        "created_at": old, "merged_at": old,
        "body": "Produced by fixed-model Factory 1",
    }
    report = status.collect(fetch_factory([], [], [pr], []), "org/repo", NOW)
    assert report["model_opened"] == []
    assert report["model_merged"] == []
