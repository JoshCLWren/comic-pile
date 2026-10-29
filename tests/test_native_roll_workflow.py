"""Keep native parity required when only its Python oracle or dependencies change."""

from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("event", ["pull_request", "push"])
@pytest.mark.parametrize(
    "changed_path",
    [
        "app/repositories/reading_shadow_repository.py",
        "app/repositories/reading_list_authoring_repository.py",
        "app/repositories/reading_overlap_decision_repository.py",
        "app/services/reading_list_evaluator.py",
        "app/services/collection_exclusion_guard.py",
        "app/models/thread.py",
        "app/models/issue.py",
        "app/database.py",
        "app/auth.py",
        "comic_pile/queue.py",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "native/roll-service/parity/test_core_inputs.py",
        "native/roll-service/src/reading_inputs.rs",
        "tests/fixtures/roll-v2/auth-matrix.json",
    ],
)
def test_oracle_changes_trigger_native_parity(event: str, changed_path: str) -> None:
    """Representative Python-only edits must select the parity workflow on both events."""
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/rust-roll.yml"
    # BaseLoader keeps YAML 1.1's 'on' key as a string rather than a boolean.
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    paths = config["on"][event]["paths"]
    assert any(fnmatchcase(changed_path, pattern) for pattern in paths), changed_path
    steps = config["jobs"]["rust-roll"]["steps"]
    assert any(
        "pytest native/roll-service/parity/" in step.get("run", "")
        for step in steps
    )
