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
* the producer has three pieces (Python fallback, workflow secret export, and
  workflow shared remote) and each is guarded separately, because a dependent
  worker pushes through the workflow and deleting only one workflow piece must
  not look like a completed retirement;
* the ordering guard catches a premature removal of any piece, a partly removed
  producer after retirement, and a removal that became due but was never
  performed;
* a completed retirement is consistent and violation-free;
* the census never mints a token and never reaches GitHub.

Pilot-era expectations live in fixed fixtures below. The live repository is
checked only through :func:`factory_shared_token_retirement.violations`, so a
correctly ordered rollout to another worker, or a completed retirement, passes
without rewriting these tests.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

retirement = importlib.import_module("factory_shared_token_retirement")
worker_app = retirement.factory_worker_github_app

PILOT_WORKER = 48
OTHER_WORKER = 11
RETIRED_WORKER = 72

# Fixed pilot-shaped roster: worker 48 is the pilot, worker 11 is not yet routed.
PILOT_ROSTER: dict[str, object] = {
    "expected_workers": [OTHER_WORKER, PILOT_WORKER],
    "retired_workers": [RETIRED_WORKER],
}


def _load(path: Path) -> dict[str, object]:
    """Load a repository JSON object for a test."""
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return dict(data)


def _workers(mapping: dict[str, object]) -> dict[str, object]:
    """Return the mutable ``workers`` object of a mapping fixture."""
    workers = mapping.setdefault("workers", {})
    assert isinstance(workers, dict)
    return workers


def _generalized_worker_entry(
    mapping: dict[str, object], worker: str
) -> dict[str, object] | None:
    """Stand-in for a fleet-wide routing gate that admits every mapped worker.

    Issue #3139 widens provisioning past the worker-48 pilot. This helper lets
    the census be exercised against that future shape without changing
    production routing inside this test.
    """
    workers = mapping.get("workers")
    if not isinstance(workers, dict):
        return None
    entry = workers.get(str(worker))
    return dict(entry) if isinstance(entry, dict) else None


def _pilot_worker_entry(
    mapping: dict[str, object], worker: str
) -> dict[str, object] | None:
    """Routing gate shaped like the worker-48 pilot: only 48 is admitted."""
    if str(worker) != str(PILOT_WORKER):
        return None
    return _generalized_worker_entry(mapping, worker)


def _pilot_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install the pilot routing gate on the production module."""
    monkeypatch.setattr(worker_app, "worker_entry", _pilot_worker_entry)


def _complete_entry(worker: int) -> dict[str, object]:
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


def _mapping_for(*workers: int) -> dict[str, object]:
    """Return a mapping fixture with a complete App row per worker."""
    return {"workers": {str(worker): _complete_entry(worker) for worker in workers}}


def _workflow_text(*, secret: bool, remote: bool) -> str:
    """Return synthetic ``free-model-factory-run.yml`` wiring."""
    lines = ["jobs:", "  factory:", "    env:"]
    if secret:
        lines.append("      PR_REBASE_TOKEN: ${{ secrets.PR_REBASE_TOKEN }}")
    if remote:
        lines.append(
            '          git remote set-url origin "https://x-access-token:'
            '${PR_REBASE_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"'
        )
    return "\n".join(lines) + "\n"


def test_pilot_scope_retains_the_shared_producer(monkeypatch: pytest.MonkeyPatch) -> None:
    """With only the pilot routed, the producer must stay and stay wired."""
    _pilot_worker(monkeypatch)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_wiring=True,
    )

    assert report["decision"] == "retain"
    assert report["dedicated_workers"] == [PILOT_WORKER]
    assert report["dependent_workers"] == [OTHER_WORKER]
    assert report["shared_producer_present"] is True
    assert retirement.violations(report) == []


def test_mapping_rows_alone_cannot_retire_the_producer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete App row without routing support is still a dependent."""
    monkeypatch.setattr(
        worker_app, "worker_entry", lambda _mapping, _worker: None
    )
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_wiring=True,
    )

    assert report["decision"] == "retain"
    assert report["dedicated_workers"] == []
    assert report["dependent_workers"] == [OTHER_WORKER, PILOT_WORKER]
    assert retirement.violations(report) == []


def test_incomplete_mapping_row_stays_dependent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed when a routed worker is missing part of its App identity."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    mapping = _mapping_for(PILOT_WORKER)
    broken = _complete_entry(OTHER_WORKER)
    broken["installation_id"] = None
    _workers(mapping)[str(OTHER_WORKER)] = broken

    report = retirement.census(
        lock=PILOT_ROSTER, mapping=mapping, python_fallback=True, workflow_wiring=True
    )
    assert report["decision"] == "retain"
    assert OTHER_WORKER in report["dependent_workers"]
    assert OTHER_WORKER not in report["dedicated_workers"]


def test_mapping_row_without_private_key_secret_stays_dependent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row missing its own key secret must not borrow worker 48's default secret."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    mapping = _mapping_for(PILOT_WORKER, OTHER_WORKER)
    partial = _complete_entry(OTHER_WORKER)
    del partial["private_key_secret"]
    _workers(mapping)[str(OTHER_WORKER)] = partial

    report = retirement.census(
        lock=PILOT_ROSTER, mapping=mapping, python_fallback=True, workflow_wiring=True
    )
    assert report["decision"] == "retain"
    assert OTHER_WORKER in report["dependent_workers"]
    assert OTHER_WORKER not in report["dedicated_workers"]


def test_full_fleet_identities_report_removal_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    """Once every active worker has its own App, every producer piece is overdue."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_wiring=True,
    )

    assert report["decision"] == "retire"
    assert report["dependent_workers"] == []
    assert report["shared_workflow_secret_export"] is True
    assert report["shared_workflow_remote"] is True
    assert report["shared_producer_present"] is True

    problems = retirement.violations(report)
    assert len(problems) == 3
    assert "Python fallback is still wired" in problems[0]
    assert "still exported in free-model-factory-run.yml" in problems[1]
    assert "still wires the shared git remote" in problems[2]


def test_partly_removed_workflow_after_retirement_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting only one workflow piece must not look like a completed retirement."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)

    only_remote_gone = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=False,
        workflow_secret_export=True,
        workflow_remote=False,
    )
    assert only_remote_gone["decision"] == "retire"
    assert only_remote_gone["shared_workflow_wiring"] is False
    problems = retirement.violations(only_remote_gone)
    assert len(problems) == 1
    assert "is still exported in free-model-factory-run.yml" in problems[0]

    only_export_gone = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=False,
        workflow_secret_export=False,
        workflow_remote=True,
    )
    assert only_export_gone["decision"] == "retire"
    assert only_export_gone["shared_workflow_wiring"] is False
    problems = retirement.violations(only_export_gone)
    assert len(problems) == 1
    assert "still wires the shared git remote" in problems[0]


def test_completed_retirement_has_no_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully dedicated fleet with both producer halves gone is consistent."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=False,
        workflow_wiring=False,
    )

    assert report["decision"] == "retire"
    assert report["dependent_workers"] == []
    assert report["shared_producer_present"] is False
    assert retirement.violations(report) == []


def test_premature_python_fallback_removal_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the Python fallback while workers depend on it must fail the guard."""
    _pilot_worker(monkeypatch)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=False,
        workflow_wiring=True,
    )

    assert report["decision"] == "retain"
    problems = retirement.violations(report)
    assert len(problems) == 1
    assert "Python fallback was removed while active workers still depend" in problems[0]
    assert str(PILOT_WORKER) not in problems[0]


def test_premature_workflow_secret_removal_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the secret export while workers depend on it must fail the guard."""
    _pilot_worker(monkeypatch)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_secret_export=False,
        workflow_remote=True,
    )

    assert report["decision"] == "retain"
    problems = retirement.violations(report)
    assert len(problems) == 1
    assert "secret export was removed" in problems[0]
    assert str(OTHER_WORKER) in problems[0]


def test_premature_workflow_remote_removal_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting the shared remote while workers depend on it must fail the guard."""
    _pilot_worker(monkeypatch)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_secret_export=True,
        workflow_remote=False,
    )

    assert report["decision"] == "retain"
    problems = retirement.violations(report)
    assert len(problems) == 1
    assert "shared git remote wiring was removed" in problems[0]
    assert str(OTHER_WORKER) in problems[0]


def test_premature_workflow_wiring_removal_is_a_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deleting both workflow pieces while workers depend on them must fail the guard."""
    _pilot_worker(monkeypatch)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_wiring=False,
    )

    assert report["decision"] == "retain"
    assert report["shared_workflow_secret_export"] is False
    assert report["shared_workflow_remote"] is False
    problems = retirement.violations(report)
    assert len(problems) == 2
    assert "secret export was removed" in problems[0]
    assert "shared git remote wiring was removed" in problems[1]


def test_retired_worker_72_never_keeps_the_shared_producer_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retired worker id is not an active dependency, whatever the mapping says."""
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    assert RETIRED_WORKER in retirement.retired_worker_ids(PILOT_ROSTER)

    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER, RETIRED_WORKER),
        python_fallback=True,
        workflow_wiring=True,
    )
    assert RETIRED_WORKER not in report["active_workers"]
    assert RETIRED_WORKER not in report["dependent_workers"]
    assert RETIRED_WORKER not in report["dedicated_workers"]


def test_empty_roster_refuses_to_retire() -> None:
    """An empty or unreadable roster is not evidence that the producer is unused."""
    report = retirement.census(
        lock={"expected_workers": [], "retired_workers": [RETIRED_WORKER]},
        mapping={"workers": {}},
        python_fallback=True,
        workflow_wiring=True,
    )
    assert report["decision"] == "retain"
    assert report["active_workers"] == []
    assert retirement.violations(report) == []


def test_census_never_mints_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reading the census must not exchange an App JWT for a token."""

    def _forbidden(**_kwargs: object) -> str:
        raise AssertionError("the retirement census must not mint an installation token")

    monkeypatch.setattr(worker_app, "mint_installation_token", _forbidden)
    monkeypatch.setattr(worker_app, "worker_entry", _generalized_worker_entry)
    report = retirement.census(
        lock=PILOT_ROSTER,
        mapping=_mapping_for(OTHER_WORKER, PILOT_WORKER),
        python_fallback=True,
        workflow_wiring=True,
    )
    assert report["decision"] == "retire"
    assert report["dedicated_workers"] == [OTHER_WORKER, PILOT_WORKER]


def test_workflow_wiring_requires_secret_export_and_remote(tmp_path: Path) -> None:
    """The workflow half is present only when the secret and remote both exist."""
    wired = tmp_path / "wired.yml"
    wired.write_text(_workflow_text(secret=True, remote=True), encoding="utf-8")
    assert retirement.shared_workflow_wiring(wired) is True
    assert retirement._workflow_components(wired) == (True, True)

    no_secret = tmp_path / "no-secret.yml"
    no_secret.write_text(_workflow_text(secret=False, remote=True), encoding="utf-8")
    assert retirement.shared_workflow_wiring(no_secret) is False
    assert retirement._workflow_components(no_secret) == (False, True)

    no_remote = tmp_path / "no-remote.yml"
    no_remote.write_text(_workflow_text(secret=True, remote=False), encoding="utf-8")
    assert retirement.shared_workflow_wiring(no_remote) is False
    assert retirement._workflow_components(no_remote) == (True, False)

    assert retirement.shared_workflow_wiring(tmp_path / "missing.yml") is False
    assert retirement._workflow_components(tmp_path / "missing.yml") == (False, False)


def test_live_repository_satisfies_the_ordering_guard() -> None:
    """The live repo is consistent, whatever stage of the rollout it is at."""
    report = retirement.census()
    assert retirement.violations(report) == []
    assert report["active_workers"] == retirement.active_worker_ids(
        _load(retirement.default_lock_path())
    )
    assert RETIRED_WORKER not in report["active_workers"]
    assert RETIRED_WORKER not in report["dependent_workers"]
    if report["active_workers"]:
        assert (report["decision"] == "retain") == bool(report["dependent_workers"])
    assert report["shared_producer_present"] == (
        report["shared_python_fallback"]
        and report["shared_workflow_secret_export"]
        and report["shared_workflow_remote"]
    )
    assert report["shared_workflow_wiring"] == (
        report["shared_workflow_secret_export"] and report["shared_workflow_remote"]
    )


def test_cli_plan_and_check_report_the_same_census(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI must expose the census and pass the guard on a consistent repo."""
    assert retirement.main(["retirement", "plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["schema"] == retirement.SCHEMA
    assert retirement.violations(plan) == []

    assert retirement.main(["retirement", "check"]) == 0
    check = json.loads(capsys.readouterr().out)
    assert check == plan


def test_cli_rejects_unknown_command(capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown subcommands must fail closed instead of printing a silent census."""
    assert retirement.main(["retirement", "delete"]) == 2
    assert "usage:" in capsys.readouterr().err
