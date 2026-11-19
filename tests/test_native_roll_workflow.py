"""Keep the native Rust workflow scoped to Rust sources after the Python removal."""

from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("event", ["pull_request", "push"])
@pytest.mark.parametrize(
    "changed_path",
    [
        "build.rs",
        "native/roll-service/src/reading_inputs.rs",
        "native/migrate/src/lib.rs",
        "native/migrate/migrations/V1__baseline.sql",
        "api/native_roll.rs",
        "tests/fixtures/roll-v2/auth-matrix.json",
    ],
)
def test_rust_changes_trigger_native_workflow(event: str, changed_path: str) -> None:
    """Representative Rust edits must select the native workflow on both events."""
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/rust-roll.yml"
    # BaseLoader keeps YAML 1.1's 'on' key as a string rather than a boolean.
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    paths = config["on"][event]["paths"]
    assert any(fnmatchcase(changed_path, pattern) for pattern in paths), changed_path


def test_no_python_oracle_steps_remain() -> None:
    """The deleted Python API cannot be a required oracle for Rust CI."""
    workflow = Path(__file__).resolve().parents[1] / ".github/workflows/rust-roll.yml"
    config = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    steps = config["jobs"]["rust-roll"]["steps"]
    text = "\n".join(step.get("run", "") for step in steps)
    assert "pytest native/roll-service/parity/" not in text
    assert "alembic upgrade head" not in text
