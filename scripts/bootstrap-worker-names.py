#!/usr/bin/env python3
"""Bootstrap worker names for the factory GitHub Apps provisioning.

This script generates display names for all active workers using the same
Faker contract as worker 48.
"""

import json
import subprocess
import sys
from pathlib import Path

PROVEN_WORKER = 48
SELF_PROVISIONING_WORKER = 54
ROSTER_LOCK_PATH = Path(__file__).resolve().parents[1] / ".github" / "factory-expected-workers.json"
DEFAULT_MAPPING_PATH = Path(".github") / "factory-worker-github-apps.json"
PROFILE_TEXT = (
    "Autonomous ComicPile Factory worker. This GitHub App is the visible push "
    "and pull-request identity for durable factory worker only. It is not a "
    "trusted factory-marker author. Trusted marker comments stay on "
    "github-actions[bot]. Model and worker number stay in human-readable pull "
    "request text."
)


def _active_worker_ids() -> list[int]:
    """Return the active durable worker ids from the canonical roster lock.

    Retired workers are excluded, and the self-provisioning worker (54) is
    excluded from scheduled provisioning.

    Returns:
        Sorted active durable worker ids.

    Raises:
        RuntimeError: When the canonical roster lock file is unavailable.
    """
    if not ROSTER_LOCK_PATH.is_file():
        raise RuntimeError(f"factory roster lock not found: {ROSTER_LOCK_PATH}")
    lock = json.loads(ROSTER_LOCK_PATH.read_text(encoding="utf-8"))
    expected = {int(worker) for worker in lock.get("expected_workers") or []}
    retired = {int(worker) for worker in lock.get("retired_workers") or []}
    return sorted(expected - retired - {SELF_PROVISIONING_WORKER})


def get_bootstrap_name(worker_number: int) -> str | None:
    """Get the bootstrap name for a worker using the factory script.

    Args:
        worker_number: Provenance key of the durable factory worker.

    Returns:
        The bootstrapped display name, or None when the bootstrap fails.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                ".github/scripts/factory_worker_github_app.py",
                "bootstrap-name",
                str(worker_number),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as error:
        print(f"Error getting bootstrap name for worker {worker_number}: {error}")
        return None


def main() -> int:
    """Generate worker names and create the mapping entries.

    Returns:
        The process exit status; nonzero when any worker bootstrap fails.

    Raises:
        RuntimeError: When the canonical roster lock file is unavailable.
    """
    print("Bootstrapping worker names for GitHub Apps provisioning...")

    workers_to_provision = [worker for worker in _active_worker_ids() if worker != PROVEN_WORKER]

    worker_names: dict[str, dict[str, object]] = {}
    failed_workers: list[int] = []

    for worker in workers_to_provision:
        print(f"Getting name for worker {worker}...")
        name = get_bootstrap_name(worker)
        if not name:
            print(f"  Failed to get name for worker {worker}")
            failed_workers.append(worker)
            continue
        worker_names[str(worker)] = {
            "worker": worker,
            "display_name": name,
            # These will be filled in later when Josh creates the actual Apps
            "app_id": None,
            "app_login": None,
            "installation_id": None,
            "app_id_secret": f"FACTORY_WORKER_{worker}_APP_ID",
            "installation_id_secret": f"FACTORY_WORKER_{worker}_INSTALLATION_ID",
            "private_key_secret": f"FACTORY_WORKER_{worker}_APP_PRIVATE_KEY",
            "profile": PROFILE_TEXT,
        }
        print(f"  Worker {worker}: {name}")

    if failed_workers:
        failed = ", ".join(str(worker) for worker in failed_workers)
        print(f"Bootstrap failed for workers: {failed}")
        print("Mapping was not updated.")
        return 1

    if not worker_names:
        print("No workers left to provision.")
        return 0

    existing_mapping: dict[str, object] = {
        "schema": "comic-pile-factory-worker-github-app-v1",
        "provenance_key": "worker",
        "notes": (
            "Bootstrap names once. Do not re-roll on later reads. "
            "Placeholders stay null until Josh creates the GitHub App."
        ),
        "faker": {
            "distribution": "Faker",
            "version": "40.40.0",
            "locale": "en_US",
            "constructor": "new Faker() per worker",
            "seed": "seed_instance(worker_number + 100)",
            "first_call": "name()",
        },
        "workers": {},
    }
    if DEFAULT_MAPPING_PATH.is_file():
        with open(DEFAULT_MAPPING_PATH, encoding="utf-8") as handle:
            existing_mapping = json.load(handle)
    existing_workers = existing_mapping.get("workers")
    existing_dict = existing_workers if isinstance(existing_workers, dict) else {}
    workers: dict[str, object] = dict(existing_dict)

    added = 0
    for key, entry in worker_names.items():
        if key in workers:
            print(f"  Worker {key}: keeping saved entry")
            continue
        workers[key] = entry
        added += 1

    if added:
        updated = dict(existing_mapping)
        updated["workers"] = workers
        with open(DEFAULT_MAPPING_PATH, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, indent=2)

    print(f"\nUpdated mapping file with {added} new workers")
    print("Workers provisioned:", ", ".join(sorted(worker_names)))
    print("\nNote: Worker 48 is already provisioned.")
    print("Note: Worker 54 (myself) is excluded as I will provision my own App separately.")
    print("\nNext step: Josh needs to create the actual GitHub Apps using these names.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
