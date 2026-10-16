"""Unit tests for the backend CI shard partitioner (``scripts/ci_backend_shard.py``)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_backend_shard.py"


def _module() -> ModuleType:
    """Import the shard partitioner without treating ``scripts/`` as a package."""
    module_name = "ci_backend_shard"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _partition(shards: int) -> list[list[str]]:
    """Return the shard partition as sorted path strings."""
    module = _module()
    return [
        sorted(str(path) for path in module.shard_test_files(index, shards))
        for index in range(1, shards + 1)
    ]


def test_shards_partition_the_suite_exactly_once() -> None:
    """Every backend test file lands in exactly one shard with no gaps."""
    partition = _partition(4)
    assigned = [path for bucket in partition for path in bucket]
    expected = sorted(str(path) for path in (ROOT / "tests").glob("test_*.py"))

    assert expected, "expected the repository to contain backend tests"
    assert sorted(assigned) == expected
    assert len(assigned) == len(set(assigned))
    assert all(bucket for bucket in partition)


def test_partition_is_deterministic() -> None:
    """Repeated runs over the same tree produce identical assignments."""
    assert _partition(3) == _partition(3)


def test_shards_are_reasonably_balanced() -> None:
    """The greedy partition keeps per-shard line loads within 1.5x the mean."""
    partition = _partition(4)
    loads = [sum(_lines(path) for path in bucket) for bucket in partition]

    average = sum(loads) / len(loads)
    assert max(loads) <= 1.5 * average


def test_invalid_shard_requests_raise() -> None:
    """Out-of-range shard counts and indices are rejected."""
    module = _module()

    with pytest.raises(ValueError):
        module.shard_test_files(0, 3)
    with pytest.raises(ValueError):
        module.shard_test_files(4, 3)
    with pytest.raises(ValueError):
        module.shard_test_files(1, 0)


def _lines(path: str) -> int:
    """Return the line count of a test file path."""
    return Path(path).read_text(encoding="utf-8").count("\n") + 1
