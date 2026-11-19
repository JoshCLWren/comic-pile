"""Regression: anti-slop lint gate uses one effective scope from root and frontend scripts."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _package_json(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _load_jsonc(relative_path: str) -> dict:
    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    text = re.sub(r"//.*", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def test_root_and_frontend_anti_slop_scripts_share_scope() -> None:
    """Root and frontend anti-slop scripts must resolve to the same effective scope."""
    root_script = _package_json("package.json")["scripts"]["lint:anti-slop"]
    frontend_script = _package_json("frontend/package.json")["scripts"]["lint:anti-slop"]

    assert "frontend" not in root_script.split(), (
        "root lint:anti-slop must not be limited to frontend/; CI runs it from repo root"
    )
    assert frontend_script.strip() == "cd .. && pnpm run lint:anti-slop", (
        "frontend lint:anti-slop must delegate to the root script so both resolve to one scope"
    )


def test_anti_slop_config_excludes_github_directory() -> None:
    """Repo-wide anti-slop config must exclude .github/ from lint scope."""
    config = _load_jsonc(".oxlintrc.json")
    ignore_patterns = config.get("ignorePatterns", [])
    assert ".github/**" in ignore_patterns, (
        "repo-wide anti-slop gate must exclude .github/** to match the intended effective scope"
    )
