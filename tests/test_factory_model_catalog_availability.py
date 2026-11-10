"""Fast regression coverage for the executable OpenCode model-catalog preflight."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WAIT_SCRIPT = ROOT / ".github/scripts/wait-opencode-model.sh"
WORKFLOW = ROOT / ".github/workflows/free-model-factory-run.yml"


@pytest.mark.parametrize(
    ("catalog", "expected_status"),
    [
        ("vendor/selected:free\nvendor/other:free\n", 0),
        ("vendor/other:free\n", 3),
        (None, 1),
    ],
)
def test_model_preflight_distinguishes_model_absence_from_catalog_failure(
    tmp_path: Path, catalog: str | None, expected_status: int
) -> None:
    """A missing model is not a failed catalog read or a successful preflight."""
    model_command = tmp_path / "mock-opencode"
    if catalog is None:
        model_command.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    else:
        model_command.write_text(
            "#!/usr/bin/env bash\n"
            '[[ "$1" == models && "$2" == --standalone ]] || exit 2\n'
            f"printf '%b' {catalog!r}\n",
            encoding="utf-8",
        )
    model_command.chmod(0o755)

    # Simulate the end of the 45-second polling window in one iteration without
    # changing the production deadline or adding a test-only runtime flag.
    bash_env = tmp_path / "bash-env"
    bash_env.write_text("sleep() { SECONDS=3600; }\n", encoding="utf-8")
    env = {
        **os.environ,
        "BASH_ENV": str(bash_env),
        "OPENCODE_BIN": str(model_command),
    }
    result = subprocess.run(
        ["bash", str(WAIT_SCRIPT), "vendor/selected:free"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == expected_status
    if expected_status == 0:
        assert "catalog ready" in result.stdout
    else:
        assert "did not expose" in result.stderr


def test_factory_workflow_records_precise_preflight_outcome() -> None:
    """A bad model cools down, but a catalog outage never retires its model."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'bash .github/scripts/wait-opencode-model.sh "$RUNTIME_MODEL"' in workflow
    assert "if (( model_wait_status == 3 )); then" in workflow
    assert "model_unavailable" in workflow
    assert "elif (( model_wait_status != 0 )); then" in workflow
    assert "control_plane_failure" in workflow
    assert "exit 1" in workflow
