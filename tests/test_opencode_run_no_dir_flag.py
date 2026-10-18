"""Regression guard: OpenCode 2 `opencode run` rejects the `--dir` flag.

Runs that passed `--dir` failed before doing any work, which broke semantic
review recovery (Actions runs 39105689321 and 39120222643). Callers must run
OpenCode from the target directory (for example `(cd "$dir" && opencode run ...)`
or `subprocess.run(..., cwd=dir)`) instead.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_SUFFIXES = {".sh", ".py", ".yml", ".yaml", ".md", ".cjs", ".mjs", ".js", ".ts"}
SKIP_PREFIXES = ("archive/",)
SELF = Path(__file__).resolve()


def _tracked_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    files = []
    for rel in output.splitlines():
        if rel.startswith(SKIP_PREFIXES):
            continue
        path = ROOT / rel
        if path.suffix in SCAN_SUFFIXES and path.is_file() and path.resolve() != SELF:
            files.append(path)
    return files


def _opencode_run_invocations(text: str) -> list[str]:
    """Return each `opencode run` / ["opencode", "run"] invocation with continuations."""
    lines = text.splitlines()
    found: list[str] = []
    for index, line in enumerate(lines):
        if not re.search(r'opencode\s+run\b|"opencode",\s*$|opencode_args=\(run\b', line):
            continue
        chunk = [line]
        cursor = index
        # Follow shell continuations and Python list literals.
        while cursor + 1 < len(lines) and (
            chunk[-1].rstrip().endswith("\\")
            or chunk[-1].rstrip().endswith(",")
            or chunk[-1].rstrip().endswith('"opencode",')
        ):
            cursor += 1
            chunk.append(lines[cursor])
            if len(chunk) > 20:
                break
        found.append("\n".join(chunk))
    return found


def test_no_opencode_run_uses_dir_flag() -> None:
    """No tracked script passes --dir to opencode run."""
    offenders = []
    for path in _tracked_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for invocation in _opencode_run_invocations(text):
            if re.search(r'(^|[\s"\'])--dir([\s"\'=]|$)', invocation):
                offenders.append(f"{path.relative_to(ROOT)}: {invocation.strip()[:160]}")
    assert not offenders, "opencode run no longer accepts --dir:\n" + "\n".join(offenders)


def test_guard_detects_dir_flag() -> None:
    """The scanner catches shell and Python --dir invocations."""
    sample = 'timeout 5s \\\n  opencode run -m "m" --agent build --dir "$ws" \\\n  "prompt"\n'
    assert any("--dir" in item for item in _opencode_run_invocations(sample))
    py_sample = 'command = [\n    "opencode",\n    "run",\n    "--dir",\n    workspace,\n]\n'
    assert any("--dir" in item for item in _opencode_run_invocations(py_sample))
