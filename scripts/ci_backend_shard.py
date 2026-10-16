"""Assign backend test files to deterministic CI shards.

The Backend Tests job is the CI critical path, so ``.github/workflows/ci.yml``
runs the suite as a GitHub Actions matrix. This module partitions
``tests/test_*.py`` into ``--shards`` disjoint groups using a greedy
longest-processing-time heuristic (file line count as the cost proxy) and prints
the files assigned to one ``--shard``.

The partition is deterministic for a fixed tree: two runs over the same
checkout always produce the same assignment, so per-shard coverage data files
stay stable and can be combined by the coverage gate.
"""

import argparse
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = REPOSITORY_ROOT / "tests"


def _line_count(path: Path) -> int:
    """Return a file's line count, used as the shard cost proxy."""
    return path.read_text(encoding="utf-8").count("\n") + 1


def shard_test_files(shard: int, shards: int) -> list[Path]:
    """Assign every backend test file to one of ``shards`` groups.

    Files are ordered largest-first (ties broken by path) and each is placed in
    the currently least loaded bucket, which keeps the per-shard line totals
    close without needing historical timing data.

    Args:
        shard: One-based index of the shard whose files to return.
        shards: Total number of shards.

    Returns:
        Sorted paths of the test files assigned to ``shard``.

    Raises:
        ValueError: If ``shards`` is less than one or ``shard`` is out of range.
    """
    if shards < 1:
        raise ValueError("shards must be at least 1")
    if not 1 <= shard <= shards:
        raise ValueError("shard must be between 1 and shards inclusive")

    weighted = sorted(
        ((_line_count(path), path) for path in TESTS_DIR.glob("test_*.py")),
        key=lambda item: (-item[0], str(item[1])),
    )

    buckets: list[list[Path]] = [[] for _ in range(shards)]
    loads = [0] * shards
    for lines, path in weighted:
        lightest = min(range(shards), key=lambda index: (loads[index], index))
        buckets[lightest].append(path)
        loads[lightest] += lines

    return sorted(buckets[shard - 1])


def main() -> None:
    """Print the space-separated test files assigned to the requested shard."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True, help="One-based shard index")
    parser.add_argument("--shards", type=int, required=True, help="Total number of shards")
    args = parser.parse_args()
    print(" ".join(str(path) for path in shard_test_files(args.shard, args.shards)))


if __name__ == "__main__":
    main()
