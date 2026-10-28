#!/usr/bin/env python3
"""Bootstrap worker names for the factory GitHub Apps provisioning.

This script generates display names for all active workers using the same
Faker contract as worker 48.
"""

import json
import subprocess
import sys
from pathlib import Path

# Active workers from factory-expected-workers.json (excluding 48 which is already done)
ACTIVE_WORKERS = [
    11, 20, 21, 41, 42, 45, 46, 49, 51, 52, 53, 54, 55, 56, 58, 60, 61, 62, 
    63, 64, 65, 68, 69, 73, 74, 75, 78, 80, 82, 83, 86, 87, 88, 89, 90, 91, 
    92, 93, 94, 95
]

# Worker 54 is myself, so exclude it from the list to be provisioned
WORKERS_TO_PROVISION = [w for w in ACTIVE_WORKERS if w != 48 and w != 54]

def get_bootstrap_name(worker_number):
    """Get the bootstrap name for a worker using the factory script."""
    try:
        result = subprocess.run([
            sys.executable, 
            ".github/scripts/factory_worker_github_app.py", 
            "bootstrap-name", 
            str(worker_number)
        ], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting bootstrap name for worker {worker_number}: {e}")
        return None

def main():
    """Generate worker names and create the mapping entries."""
    print("Bootstrapping worker names for GitHub Apps provisioning...")
    
    worker_names = {}
    
    for worker in WORKERS_TO_PROVISION:
        print(f"Getting name for worker {worker}...")
        name = get_bootstrap_name(worker)
        if name:
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
                "profile": "Autonomous ComicPile Factory worker. This GitHub App is the visible push and pull-request identity for durable factory worker only. It is not a trusted factory-marker author. Trusted marker comments stay on github-actions[bot]. Model and worker number stay in human-readable pull request text."
            }
            print(f"  Worker {worker}: {name}")
        else:
            print(f"  Failed to get name for worker {worker}")
    
    # Load existing mapping
    mapping_path = Path(".github/factory-worker-github-apps.json")
    if mapping_path.exists():
        with open(mapping_path) as f:
            existing_mapping = json.load(f)
    else:
        existing_mapping = {
            "schema": "comic-pile-factory-worker-github-app-v1",
            "provenance_key": "worker",
            "notes": "Bootstrap names once. Do not re-roll on later reads. Placeholders stay null until Josh creates the GitHub App.",
            "faker": {
                "distribution": "Faker",
                "version": "40.40.0",
                "locale": "en_US",
                "constructor": "new Faker() per worker",
                "seed": "seed_instance(worker_number + 100)",
                "first_call": "name()"
            },
            "workers": {}
        }
    
    # Add new workers to existing mapping
    existing_mapping["workers"].update(worker_names)
    
    # Save updated mapping
    with open(mapping_path, 'w') as f:
        json.dump(existing_mapping, f, indent=2)
    
    print(f"\nUpdated mapping file with {len(worker_names)} new workers")
    print("Workers provisioned:", ", ".join(map(str, WORKERS_TO_PROVISION)))
    print("\nNote: Worker 48 is already provisioned.")
    print("Note: Worker 54 (myself) is excluded as I will provision my own App separately.")
    print("\nNext step: Josh needs to create the actual GitHub Apps using these names.")

if __name__ == "__main__":
    main()