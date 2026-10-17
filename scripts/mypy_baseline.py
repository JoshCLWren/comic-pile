"""Run the strict-clean ratchet and produce the full migration inventory."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "mypy-clean.json"
INVENTORY = ROOT / "docs/typing/mypy-inventory.json"


@dataclass(frozen=True)
class Diagnostic:
    """One structured mypy diagnostic."""

    file: str
    line: int
    code: str
    severity: str
    message: str


def parse_diagnostics(output: str) -> list[Diagnostic]:
    """Parse JSON-lines diagnostics, rejecting unexpected checker output.

    Args:
        output: Mypy JSON-lines stdout.

    Returns:
        Validated diagnostics.
    """
    result = []
    for line in output.splitlines():
        raw: object = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("Expected a mypy diagnostic object")
        file, number = raw.get("file"), raw.get("line")
        code, severity, message = raw.get("code"), raw.get("severity"), raw.get("message")
        if not (
            isinstance(file, str) and isinstance(number, int)
            and isinstance(code, (str, type(None))) and isinstance(severity, str)
            and isinstance(message, str)
        ):
            raise ValueError("Invalid mypy diagnostic fields")
        path = Path(file)
        if path.is_absolute():
            path = path.relative_to(ROOT)
        result.append(Diagnostic(path.as_posix(), number, code or "uncoded", severity, message))
    return sorted(result, key=lambda d: (d.file, d.line, d.code, d.message))


def load_clean(surface: set[str]) -> list[str]:
    """Validate the explicit, nonempty clean-file manifest.

    Args:
        surface: All inventoried Python paths.

    Returns:
        Sorted strict-clean file paths.
    """
    raw: object = json.loads(MANIFEST.read_text())
    if not isinstance(raw, list) or not raw:
        raise ValueError("Clean manifest must be a nonempty list of exact file paths")
    paths: list[str] = []
    for path in raw:
        if not isinstance(path, str) or path not in surface:
            raise ValueError(f"Clean manifest path is outside the Python surface: {path!r}")
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate clean manifest paths")
    return sorted(paths)


def classify(code: str) -> tuple[str, str]:
    """Group diagnostics into conservative migration families.

    Args:
        code: Mypy error code.

    Returns:
        Family and triage classification; interface findings need human inspection.
    """
    if code in {"no-untyped-def", "no-untyped-call", "type-arg", "var-annotated"}:
        return "annotation-completeness", "local-typing-cleanup"
    if code in {"import-untyped", "import-not-found", "untyped-decorator"}:
        return "dependency-typing", "design-interface-review"
    if code in {"no-any-return", "no-any-unimported"}:
        return "dynamic-boundary", "design-interface-review"
    if code in {"redundant-cast", "unused-ignore"}:
        return "obsolete-typing-workaround", "local-typing-cleanup"
    return "contract-and-narrowing", "design-interface-review"


def build_inventory(surface: set[str], diagnostics: list[Diagnostic]) -> dict[str, object]:
    """Build a complete file inventory with code/family counts and raw evidence.

    Args:
        surface: Explicit Python files, including clean files.
        diagnostics: Full checker diagnostics, including imported modules.

    Returns:
        Deterministic machine-readable migration inventory.
    """
    modules = []
    errors = [d for d in diagnostics if d.severity == "error"]
    for path in sorted(surface | {d.file for d in diagnostics}):
        found = [d for d in errors if d.file == path]
        groups = Counter((d.code, *classify(d.code)) for d in found)
        modules.append({
            "path": path,
            "module": path.removesuffix(".py").replace("/", "."),
            "package": path.split("/")[0],
            "explicit_surface": path in surface,
            "error_count": len(found),
            "groups": [
                {"code": code, "family": family, "triage": triage, "count": count}
                for (code, family, triage), count in sorted(groups.items())
            ],
        })
    return {
        "schema_version": 1,
        "mypy_version": subprocess.check_output(
            [sys.executable, "-m", "mypy", "--version"], text=True,
        ).strip(),
        "profile": "pyproject.toml:tool.mypy (strict, Python 3.14)",
        "surface": sorted(surface),
        "error_count": len(errors),
        "triage_note": "Conservative code-based triage, not proof of a runtime defect; inspect evidence before changing interfaces.",
        "modules": modules,
        "diagnostics": [asdict(d) for d in diagnostics],
    }


def check_clean(clean: list[str], diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Select regressions in strict-clean scopes without suppressing other evidence.

    Args:
        clean: Explicit clean paths.
        diagnostics: All mypy diagnostics.

    Returns:
        Errors in the clean scope.
    """
    return [d for d in diagnostics if d.severity == "error" and d.file in clean]


def main() -> int:
    """Run the checker and gate or refresh the inventory.

    Returns:
        Zero on success, one on a clean-scope regression, two on tool/config failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "inventory"])
    args = parser.parse_args()
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"]
    surface = {
        p.relative_to(ROOT).as_posix()
        for entry in config["files"]
        for p in ([ROOT / entry] if (ROOT / entry).is_file() else (ROOT / entry).rglob("*.py"))
    }
    clean = load_clean(surface)
    completed = subprocess.run(
        [sys.executable, "-m", "mypy", "--config-file", "pyproject.toml", "--output", "json"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if completed.returncode not in (0, 1) or completed.stderr:
        print(completed.stderr or completed.stdout, file=sys.stderr)
        return 2
    diagnostics = parse_diagnostics(completed.stdout)
    if completed.returncode == 1 and not any(d.severity == "error" for d in diagnostics):
        raise ValueError("Mypy failed without error diagnostics")
    if args.mode == "inventory":
        INVENTORY.parent.mkdir(parents=True, exist_ok=True)
        INVENTORY.write_text(json.dumps(build_inventory(surface, diagnostics), indent=2) + "\n")
        print(f"Wrote full strict inventory to {INVENTORY.relative_to(ROOT)}")
    failures = check_clean(clean, diagnostics)
    for d in failures:
        print(f"{d.file}:{d.line}: {d.message} [{d.code}]")
    print(f"Strict-clean ratchet: {len(clean)} files, {len(failures)} regressions")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
