#!/usr/bin/env python3
"""Strict path-only classifier for ComicPile's factory-infrastructure CI fast path.

Unknown files, application code, CI policy, secrets and empty diffs use full CI.
A factory prefix is not sufficient to classify changes outside these directories.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ALLOWED = tuple(re.compile(pattern) for pattern in (
    r"\.github/workflows/(?:factory-[\w.-]+|fixed-model-factory-[\w.-]+|free-model-factory-[\w.-]+|local-ollama-review)\.yml",
    r"\.github/scripts/(?:factory[_-][\w.-]+|free-model-factory-[\w.-]+|fixed-model-[\w.-]+|local_review_contract\.py)",
    r"\.github/actions/factory-[\w.-]+/[\w./-]+",
    r"\.github/factory-[\w.-]+\.json",
    r"scripts/factory-run",
    r"tests/test_factory_[\w.-]+\.py",
    r"docs/factory/[\w./-]+",
))


def factory_only(paths: list[str]) -> bool:
    """Fail closed for empty diffs, unexpected or unsafe paths."""
    return bool(paths) and all(
        not path.startswith("/") and ".." not in Path(path).parts
        and any(pattern.fullmatch(path) for pattern in ALLOWED)
        for path in paths
    )


def main() -> int:
    """Read the authoritative git diff and print a single boolean classification."""
    if len(sys.argv) != 2:
        print("usage: factory_ci_scope.py <null-delimited-changed-paths>", file=sys.stderr)
        return 2
    data = Path(sys.argv[1]).read_bytes()
    paths = [value.decode("utf-8") for value in data.split(b"\0") if value]
    print("true" if factory_only(paths) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
