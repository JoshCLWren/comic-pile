"""Keep the anti-slop gate scope identical in local and CI invocations."""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_root_and_frontend_anti_slop_scripts_cover_same_repository_scope() -> None:
    """Both commands lint the repository root, including api/, except .github/."""
    root_package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    frontend_package = json.loads(
        (REPO_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    root_command = root_package["scripts"]["lint:anti-slop"]
    frontend_command = frontend_package["scripts"]["lint:anti-slop"]

    expected = "oxlint --config .oxlintrc.json --ignore-pattern '.github/**'"
    assert root_command == expected
    assert frontend_command == f"cd .. && {expected}"
