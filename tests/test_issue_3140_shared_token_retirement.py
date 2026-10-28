"""Retirement gate for the shared ``PR_REBASE_TOKEN`` producer (issue #3140).

Issue #3140 allows removing the shared push/pull-request producer only when no
active worker still depends on it, and explicitly says retired worker 72 is not
a reason to keep it. These tests pin the executable form of that condition:

* the census reads the active roster and the persisted worker-App mapping, so
  dependents are derived from durable state rather than guessed;
* worker 72 (retired) can never appear as a dependent;
* a mapping row alone is not enough: the production routing decision must
  already select the installation token, which keeps the census aligned with
  the code that actually pushes;
* the ordering guard catches a premature removal and a removal that became due
  but was never performed;
* the census never mints a token and never reaches GitHub.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

retirement = importlib.import_module("factory_shared_token_retirement")
worker_app = retirement.factory_worker_github_app

REPO = SCRIPTS.parents[1]
LOCK_PATH = REPO / ".github" / "factory-expected-workers.json"
MAPPING_PATH = REPO / ".github" / "factory-worker-github-apps.json"
PILOT_WORKER = 48
RETIRED_WORKER = 72


def _load(path: Path) -> dict[str, Any]:
    """Load a repository JSON object for a test."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _generalized_worker_entry(
    mapping: dict[str, Any], worker: str
) -> dict[str, Any] | None:
    """Stand-in for a fleet-wide routing gate that admits every mapped worker.

    Issue #3139 widens provisioning past the worker-48 pilot. This helper lets
    the census be exercised against that future shape without changing
    production routing inside this test.
    """
    workers = mapping.get("workers")
    if not isinstance(workers, dict):
        return None
    entry = workers.get(str(worker))
    return entry if isinstance(entry, dict) else None


def _complete_entry(worker: int) -> dict[str, Any]:
    """Return a mapping row that looks live-verified for one worker."""
    return {
        "worker": worker,
        "display_name": f"Worker {worker}",
        "app_id": 900000 + worker,
        "app_login": f"worker-{worker}[bot]",
        "installation_id": 800000 + worker,
        "app_id_secret": f"FACTORY_WORKER_{worker}_APP_ID",
        "installation_id_secret": f"FACTORY_WORKER_{worker}_INSTALLATION_ID",
        "private_key_secret": f"FACTORY_WORKER_{worker}_APP_PRIVATE_KEY",
        "profile": "Autonomous ComicPile Factory worker test fixture.",
    }


def _fleet_mapping(lock: dict[str, Any]) -> dict[str, Any]:
    """Return a mapping where every active worker has a complete App row."""
    mapping = _load(MAPPING_PATH)
    workers = mapping.setdefault("workers", {})
    assert isinstance(workers, dict)
    for worker in retirement.active_worker_ids(lock):
        workers[str(worker)] = _complete_entry(worker)
    return mapping


def test_current_roster_still_depends_on_the_shared_producer() -> None:
    """Today only the worker-48 pilot is off the shared producer."""
    lock = _load(LOCK_PATH)
    report = retirement.census(lock=lock, mapping=_load(MAPPING_PATH))

    active = retirement.active_worker_ids(lock)
    assert report["decision"] == "retain"
    assert report["dedicated_workers"] == [PILOT_WORKER]
    assert report["dependent_workers"] == [w for w in active if w != PILOT_WORKER]
    assert report["shared_producer_present"] is True
    assert retirement.violations(report) == []


def test_retired_worker_72_never_keeps_the_shared_producer_alive() -> None:
    """A retired worker id is not an active dependency, whatever the mapping says."""
    lock = _load(LOCK_PATH)
    assert RETIRED_WORKER in lock["retired_workers"]
    assert RETIRED_WORKER not in lock["expected_workers"]

    report = retirement.census(lock=lock, mapping=_load(MAPPING_PATH))
    assert RETIRED_WORKER not in report["active_workers"]
    assert RETIRED_WORKER not in report["dependent_workers"]
    assert RETIRED_WORKER not in report["dedicated_workers"]


def test_mapping_row_without_routing_support_stays_dependent() -> None:
    """A non-pilot mapping row cannot retire the producer until routing admits it."""
    lock = _load(LOCK_PATH)
    mapping = _load(MAPPING_PATH)
    workers = mapping.setdefault("workers", {})
    assert isinstance(workers, dict)
    workers["11"] = _complete_entry(11)

    report = retirement.census(lock=lock, mapping=mapping)
    assert report["decision"] == "retain"
    assert 11 in report["dependent_workers"]
    assert 11 not in report["dedicated_workers"]


def test_incomplete_mapping_row_stays_dependent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed when a routed worker is missing part of its App identity."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    lock = _load(LOCK_PATH)
    mapping = _fleet_mapping(lock)
    workers = mapping["workers"]
    assert isinstance(workers, dict)
    broken = _complete_entry(11)
    broken["installation_id"] = None
    workers["11"] = broken

    report = retirement.census(lock=lock, mapping=mapping)
    assert report["decision"] == "retain"
    assert 11 in report["dependent_workers"]
    assert 11 not in report["dedicated_workers"]


def test_full_fleet_identities_report_removal_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once every active worker has its own App, the shared producer is overdue."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    lock = _load(LOCK_PATH)
    mapping = _fleet_mapping(lock)

    report = retirement.census(lock=lock, mapping=mapping)
    assert report["decision"] == "retire"
    assert report["dependent_workers"] == []
    assert report["shared_producer_present"] is True

    problems = retirement.violations(report)
    assert len(problems) == 1
    assert "still wired" in problems[0]


def test_premature_removal_is_a_violation() -> None:
    """Deleting the producer while workers depend on it must fail the guard."""
    report = retirement.census(
        lock=_load(LOCK_PATH),
        mapping=_load(MAPPING_PATH),
        producer_present=False,
    )
    assert report["decision"] == "retain"
    problems = retirement.violations(report)
    assert len(problems) == 1
    assert "was removed while active workers still depend on it" in problems[0]
    assert str(PILOT_WORKER) not in problems[0].rsplit(": ", 1)[1].replace(" ", "").split(",")


def test_empty_roster_refuses_to_retire() -> None:
    """An empty or unreadable roster is not evidence that the producer is unused."""
    report = retirement.census(
        lock={"expected_workers": [], "retired_workers": [RETIRED_WORKER]},
        mapping={"workers": {}},
        producer_present=True,
    )
    assert report["decision"] == "retain"
    assert report["active_workers"] == []
    assert retirement.violations(report) == []


def test_census_never_mints_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the census must not exchange an App JWT for a token."""

    def _forbidden(**_kwargs: object) -> str:
        raise AssertionError("the retirement census must not mint an installation token")

    monkeypatch.setattr(worker_app, "mint_installation_token", _forbidden)
    report = retirement.census(
        lock=_load(LOCK_PATH),
        mapping=_load(MAPPING_PATH),
        producer_present=True,
    )
    assert report["dedicated_workers"] == [PILOT_WORKER]


def test_cli_plan_and_check_report_the_same_census(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI must expose the census and pass the guard on a consistent repo."""
    assert retirement.main(["retirement", "plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == retirement.SCHEMA
    assert plan["decision"] == "retain"

    assert retirement.main(["retirement", "check"]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check == plan


def test_cli_rejects_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown subcommands must fail closed instead of printing a silent census."""
    assert retirement.main(["retirement", "delete"]) == 2
    assert "usage:" in capsys.readouterr().err
