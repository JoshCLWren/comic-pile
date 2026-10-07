"""Regression coverage for strict-clean gating and complete inventory evidence."""

import json
from pathlib import Path

import pytest

from scripts import mypy_baseline as baseline


def test_real_checker_ratchets_clean_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on a real clean-scope type regression while inventory retains legacy errors."""
    clean = tmp_path / "clean.py"
    clean.write_text('value: int = "wrong"\n')
    (tmp_path / "legacy.py").write_text('other: int = "wrong"\n')
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mypy]\nstrict = true\nfiles = ["clean.py", "legacy.py"]\n'
    )
    manifest = tmp_path / "mypy-clean.json"
    manifest.write_text('["clean.py"]\n')
    inventory = tmp_path / "inventory.json"
    monkeypatch.setattr(baseline, "ROOT", tmp_path)
    monkeypatch.setattr(baseline, "MANIFEST", manifest)
    monkeypatch.setattr(baseline, "INVENTORY", inventory)
    monkeypatch.setattr("sys.argv", ["mypy_baseline.py", "inventory"])
    assert baseline.main() == 1
    raw = json.loads(inventory.read_text())
    assert raw["error_count"] == 2
    assert {d["file"] for d in raw["diagnostics"]} == {"clean.py", "legacy.py"}
    clean.write_text("value: int = 1\n")
    monkeypatch.setattr("sys.argv", ["mypy_baseline.py", "check"])
    assert baseline.main() == 0


@pytest.mark.parametrize("content", ['[]', '["missing.py"]', '["a.py", "a.py"]'])
def test_invalid_manifest_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    """Empty, stale and duplicate manifests cannot quietly disable the gate."""
    manifest = tmp_path / "clean.json"
    manifest.write_text(content)
    monkeypatch.setattr(baseline, "MANIFEST", manifest)
    with pytest.raises(ValueError):
        baseline.load_clean({"a.py"})


@pytest.mark.parametrize("output", ['not json', '[]', '{"file": "a.py"}'])
def test_malformed_checker_output_fails_closed(output: str) -> None:
    """Tool output errors must never be mistaken for clean checks."""
    with pytest.raises(ValueError):
        baseline.parse_diagnostics(output)


def test_inventory_includes_clean_modules_and_imported_errors() -> None:
    """Include zero-error modules and transitive evidence with useful triage."""
    diagnostic = baseline.Diagnostic("imported.py", 2, "no-any-return", "error", "Dynamic")
    inventory = baseline.build_inventory({"clean.py"}, [diagnostic])
    modules = inventory["modules"]
    assert isinstance(modules, list)
    assert modules[0]["path"] == "clean.py"
    assert modules[0]["error_count"] == 0
    assert modules[1]["explicit_surface"] is False
    assert modules[1]["groups"][0]["triage"] == "design-interface-review"
