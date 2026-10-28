#!/usr/bin/env python3
"""Shared ``PR_REBASE_TOKEN`` retirement census and ordering guard (issue #3140).

The shared push and pull-request producer may be removed only after every
*active* factory worker resolves to its own GitHub App installation token.
This module turns that sentence into executable state:

* the active roster comes from ``.github/factory-expected-workers.json``, so a
  retired worker (for example retired worker 72) can never keep the shared
  producer alive;
* a worker counts as independent only when the persisted
  ``.github/factory-worker-github-apps.json`` entry is complete *and* the real
  routing decision in :mod:`factory_worker_github_app` already selects the
  installation token for it. Entries are committed only after live installation
  verification, so mapping completeness is the durable proof of provisioning;
* the producer itself has two halves that must be removed together: the Python
  fallback in :mod:`factory_worker_github_app` and the ``free-model-factory-run``
  workflow wiring that exports the secret and configures the shared git remote.
  A dependent worker pushes through the workflow wiring, so a probe that only
  exercises the Python fallback would miss a half-removed producer.

The census never mints a token and never calls GitHub. It exercises the shared
fallback through :func:`factory_worker_github_app.resolve_push_credential` and
reads the workflow file, so a premature deletion of either half is observable.

``plan`` prints the census as JSON. ``check`` prints the census and exits
non-zero when the repository disagrees with it, which catches both a premature
removal and a removal that became due and was forgotten.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict

import factory_worker_github_app

_HERE = Path(__file__).resolve().parent

SCHEMA = "comic-pile-factory-shared-token-retirement-v1"
SHARED_TOKEN_NAME = "PR_REBASE_TOKEN"
# Worker "0" has no mapping entry, so the shared fallback must answer for it.
_CENSUS_PROBE_WORKER = "0"
_SENTINEL_TOKEN = "shared-producer-census-sentinel"
_DECISIONS = ("retain", "retire")
_SECRET_EXPORT = f"{SHARED_TOKEN_NAME}: ${{{{ secrets.{SHARED_TOKEN_NAME} }}}}"
_REMOTE_STEP = "git remote set-url origin"


class RetirementCensus(TypedDict):
    """JSON-ready census of shared-producer dependents and wiring.

    Attributes:
        schema: Census schema identifier.
        shared_token: Shared credential this census orders.
        decision: ``retain`` while a dependent remains, else ``retire``.
        reason: Human-readable explanation of ``decision``.
        active_workers: Active roster, retired workers excluded.
        dedicated_workers: Active workers already on their own installation token.
        dependent_workers: Active workers still resolving to the shared token.
        shared_python_fallback: Whether the Python fallback still answers.
        shared_workflow_wiring: Whether the factory workflow exports and wires the token.
        shared_producer_present: Whether both halves of the producer still exist.
    """

    schema: str
    shared_token: str
    decision: str
    reason: str
    active_workers: list[int]
    dedicated_workers: list[int]
    dependent_workers: list[int]
    shared_python_fallback: bool
    shared_workflow_wiring: bool
    shared_producer_present: bool


def _repo_root() -> Path:
    """Return the repository root that owns ``.github/``."""
    return _HERE.parents[1]


def default_lock_path() -> Path:
    """Return the active-roster lock path."""
    return _repo_root() / ".github" / "factory-expected-workers.json"


def default_mapping_path() -> Path:
    """Return the persisted worker to App mapping path."""
    return factory_worker_github_app.DEFAULT_MAPPING


def default_workflow_path() -> Path:
    """Return the fixed-model factory workflow that wires the shared producer."""
    return _repo_root() / ".github" / "workflows" / "free-model-factory-run.yml"


def _load_object(path: Path, label: str) -> dict[str, object]:
    """Load a JSON object, failing closed on anything else."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} {path} must be a JSON object")
    return dict(data)


def _int_set(value: object, label: str) -> set[int]:
    """Coerce a JSON list of worker numbers to a set of ints."""
    if value is None:
        return set()
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a JSON list")
    workers: set[int] = set()
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            raise RuntimeError(f"{label} entries must be integers, got {item!r}")
        workers.add(item)
    return workers


def active_worker_ids(lock: Mapping[str, object]) -> list[int]:
    """Return sorted active worker ids: expected workers minus retired workers.

    A retired worker is never an active dependency, so a retired id in the lock
    cannot justify keeping the shared producer.

    Args:
        lock: Parsed ``factory-expected-workers.json`` content.

    Returns:
        Sorted active worker ids.
    """
    expected = _int_set(lock.get("expected_workers"), "expected_workers")
    retired = _int_set(lock.get("retired_workers"), "retired_workers")
    return sorted(expected - retired)


def retired_worker_ids(lock: Mapping[str, object]) -> list[int]:
    """Return sorted retired worker ids from the roster lock.

    Args:
        lock: Parsed ``factory-expected-workers.json`` content.

    Returns:
        Sorted retired worker ids.
    """
    return sorted(_int_set(lock.get("retired_workers"), "retired_workers"))


def _private_key_secret(entry: Mapping[str, object]) -> str:
    """Return the private-key secret name for a mapping entry."""
    configured = str(entry.get("private_key_secret") or "").strip()
    return configured or "FACTORY_WORKER_48_APP_PRIVATE_KEY"


def worker_has_dedicated_identity(worker: int, mapping: Mapping[str, object]) -> bool:
    """Return whether ``worker`` already resolves to its own installation token.

    The answer comes from the production routing decision, not from a parallel
    copy of it: a mapping row is enough only when
    :func:`factory_worker_github_app.credential_decision` selects ``installation``
    for that worker. A complete mapping row for a worker the routing gate does
    not yet admit stays on the shared producer, which is why this census cannot
    report a false retirement while the pilot scope is still worker 48 only.

    Args:
        worker: Durable worker number.
        mapping: Parsed ``factory-worker-github-apps.json`` content.

    Returns:
        True when the worker is fully off the shared producer.
    """
    entry = factory_worker_github_app.worker_entry(mapping, str(worker))
    if entry is None:
        return False
    env = {_private_key_secret(entry): factory_worker_github_app.TEST_KEY_SENTINEL}
    decision = factory_worker_github_app.credential_decision(str(worker), env, mapping)
    return decision["source"] == "installation"


def shared_python_fallback() -> bool:
    """Return whether the Python push/PR fallback still exists.

    Exercises :func:`factory_worker_github_app.resolve_push_credential` with a
    worker that has no App mapping, so the probe observes the real fallback
    instead of grepping source text.
    """
    env = {"FACTORY_WORKER": _CENSUS_PROBE_WORKER, SHARED_TOKEN_NAME: _SENTINEL_TOKEN}
    try:
        source, token = factory_worker_github_app.resolve_push_credential(env)
    except RuntimeError:
        return False
    return source == "pr_rebase" and token == _SENTINEL_TOKEN


def shared_workflow_wiring(path: Path | None = None) -> bool:
    """Return whether the factory workflow still supplies the shared producer.

    A dependent worker pushes through ``free-model-factory-run.yml``: the job
    env exports ``secrets.PR_REBASE_TOKEN`` and a step points ``origin`` at a URL
    containing ``${PR_REBASE_TOKEN}``. Checking only the Python fallback would
    report ``True`` after the workflow half was deleted, so this probe reads the
    workflow and fails closed when either half of the wiring is gone.

    Args:
        path: Workflow path override for tests.

    Returns:
        True when the workflow still exports the secret and wires the remote.
    """
    target = path or default_workflow_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return False
    if _SECRET_EXPORT not in text:
        return False
    return any(
        _REMOTE_STEP in line and SHARED_TOKEN_NAME in line for line in text.splitlines()
    )


def census(
    *,
    lock: Mapping[str, object] | None = None,
    mapping: Mapping[str, object] | None = None,
    python_fallback: bool | None = None,
    workflow_wiring: bool | None = None,
    lock_path: Path | None = None,
    mapping_path: Path | None = None,
    workflow_path: Path | None = None,
) -> RetirementCensus:
    """Build the retirement census from durable repository state.

    Args:
        lock: Parsed roster lock. Loaded from ``lock_path`` when omitted.
        mapping: Parsed worker App mapping. Loaded from ``mapping_path`` when omitted.
        python_fallback: Override for the Python-fallback probe.
        workflow_wiring: Override for the workflow-wiring probe.
        lock_path: Roster lock path used only when ``lock`` is omitted.
        mapping_path: App mapping path used only when ``mapping`` is omitted.
        workflow_path: Workflow path used only when ``workflow_wiring`` is omitted.

    Returns:
        JSON-ready census describing the decision and its dependents.
    """
    loaded_lock = (
        lock
        if lock is not None
        else _load_object(lock_path or default_lock_path(), "roster lock")
    )
    loaded_mapping = (
        mapping
        if mapping is not None
        else _load_object(mapping_path or default_mapping_path(), "worker App mapping")
    )
    active = active_worker_ids(loaded_lock)
    dedicated = [
        worker for worker in active if worker_has_dedicated_identity(worker, loaded_mapping)
    ]
    dependent = [worker for worker in active if worker not in dedicated]
    fallback = shared_python_fallback() if python_fallback is None else python_fallback
    wiring = (
        shared_workflow_wiring(workflow_path) if workflow_wiring is None else workflow_wiring
    )

    if not active:
        # A missing roster is not evidence that the producer is unused.
        decision = "retain"
        reason = "no active workers are recorded; refusing to retire on an empty roster"
    elif dependent:
        decision = "retain"
        reason = f"{len(dependent)} active worker(s) still resolve to {SHARED_TOKEN_NAME}"
    else:
        decision = "retire"
        reason = "every active worker resolves to its own installation token"

    return {
        "schema": SCHEMA,
        "shared_token": SHARED_TOKEN_NAME,
        "decision": decision,
        "reason": reason,
        "active_workers": active,
        "dedicated_workers": dedicated,
        "dependent_workers": dependent,
        "shared_python_fallback": fallback,
        "shared_workflow_wiring": wiring,
        "shared_producer_present": fallback and wiring,
    }


def violations(report: RetirementCensus) -> list[str]:
    """Return ordering violations for a census report.

    Two failures matter: removing either half of the shared producer while an
    active worker still depends on it, and leaving either half wired after every
    worker moved off. Both halves are checked separately so a half-removed
    producer cannot look consistent.

    Args:
        report: Census returned by :func:`census`.

    Returns:
        Human-readable violations, empty when the repository is consistent.
    """
    found: list[str] = []
    decision = report["decision"]
    dependent = report["dependent_workers"]
    fallback = report["shared_python_fallback"]
    wiring = report["shared_workflow_wiring"]
    if decision not in _DECISIONS:
        found.append(f"unknown retirement decision: {decision!r}")
        return found
    if not report["active_workers"]:
        # An empty roster is not evidence either way, so it cannot order a removal.
        return found
    dependents = ", ".join(str(worker) for worker in dependent)
    if dependent:
        if not fallback:
            found.append(
                f"{SHARED_TOKEN_NAME} Python fallback was removed while active workers "
                f"still depend on it: {dependents}"
            )
        if not wiring:
            found.append(
                f"{SHARED_TOKEN_NAME} workflow wiring was removed while active workers "
                f"still depend on it: {dependents}"
            )
        return found
    if fallback:
        found.append(
            f"every active worker has its own installation token but the {SHARED_TOKEN_NAME} "
            "Python fallback is still wired; retire the shared producer"
        )
    if wiring:
        found.append(
            f"every active worker has its own installation token but {SHARED_TOKEN_NAME} "
            "is still wired in free-model-factory-run.yml; retire the shared producer"
        )
    return found


def _flag(argv: Sequence[str], name: str) -> str:
    """Return the value of ``--name VALUE`` or an empty string."""
    if name in argv:
        index = list(argv).index(name)
        if index + 1 < len(argv):
            return str(argv[index + 1])
    return ""


def main(argv: list[str]) -> int:
    """CLI entry point: ``plan`` for the census, ``check`` for the ordering guard."""
    if len(argv) < 2 or argv[1] not in {"plan", "check"}:
        print(
            "usage: factory_shared_token_retirement.py plan|check [--lock PATH] [--mapping PATH]",
            file=sys.stderr,
        )
        return 2
    lock_path = Path(_flag(argv, "--lock")) if _flag(argv, "--lock") else None
    mapping_path = Path(_flag(argv, "--mapping")) if _flag(argv, "--mapping") else None
    try:
        report = census(lock_path=lock_path, mapping_path=mapping_path)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    if argv[1] == "plan":
        return 0
    problems = violations(report)
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
