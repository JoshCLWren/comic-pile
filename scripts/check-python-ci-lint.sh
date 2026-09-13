#!/usr/bin/env bash
# Exact GitHub CI parity for the python-lint and python-typecheck jobs.
#
# CI runs these two commands with no path arguments:
#   ruff check .
#   ty check --error-on-warning
#
# Path-filtered invocations are not a valid substitute. Re-run this script
# after every later Python edit; a green run is invalid the moment sources change.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -f "pyproject.toml" ]; then
    echo "ERROR: Run from repository root." >&2
    exit 1
fi

run_tool() {
    local tool="$1"
    shift
    if command -v "$tool" >/dev/null 2>&1; then
        "$tool" "$@"
        return
    fi
    if command -v uv >/dev/null 2>&1; then
        uv run "$tool" "$@"
        return
    fi
    echo "ERROR: ${tool} is not installed. Run: uv sync --all-extras" >&2
    exit 1
}

if [ -z "${VIRTUAL_ENV:-}" ]; then
    if [ -f ".venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source ".venv/bin/activate"
    elif [ -f .git ]; then
        GIT_COMMON_DIR="$(git rev-parse --git-common-dir 2>/dev/null || true)"
        if [ -n "$GIT_COMMON_DIR" ]; then
            MAIN_REPO_DIR="$(dirname "$GIT_COMMON_DIR")"
            if [ -f "$MAIN_REPO_DIR/.venv/bin/activate" ]; then
                # shellcheck disable=SC1091
                source "$MAIN_REPO_DIR/.venv/bin/activate"
            fi
        fi
    fi
fi

echo "Running CI-parity Python lint: ruff check ."
run_tool ruff check .

echo "Running CI-parity Python type check: ty check --error-on-warning"
run_tool ty check --error-on-warning

echo "Python CI lint and type check passed."
