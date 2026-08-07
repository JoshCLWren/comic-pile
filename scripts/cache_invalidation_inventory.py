#!/usr/bin/env python3
"""Inventory cache readers and invalidation paths for bounded-budget migration.

This tool intentionally uses static analysis so cache-budget work can account for
all production call sites without importing the application or opening Redis/DB
connections. It reports cached functions and invalidation calls, including whether
an invalidation can traverse the Redis keyspace, and can fail CI while the bounded
cache migration is incomplete.
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

CacheKind = Literal["cached", "generation_cached"]
InvalidationKind = Literal[
    "invalidate_cache",
    "clear_pattern",
    "invalidate_user_cache",
    "invalidate_user_caches",
]

_CACHE_DECORATORS = frozenset({"cached", "generation_cached"})
_INVALIDATION_CALLS = frozenset(
    {"invalidate_cache", "clear_pattern", "invalidate_user_cache", "invalidate_user_caches"}
)
_UNBOUNDED_INVALIDATIONS = frozenset({"invalidate_cache", "clear_pattern"})
_DEFAULT_ROOTS = (Path("app"), Path("comic_pile"))


@dataclass(frozen=True, slots=True)
class CachedFunction:
    """One function decorated with a remote-cache decorator."""

    path: str
    line: int
    function: str
    cache_kind: CacheKind


@dataclass(frozen=True, slots=True)
class InvalidationCall:
    """One cache invalidation call discovered in production source."""

    path: str
    line: int
    function: str
    invalidation_kind: InvalidationKind
    bounded: bool


@dataclass(frozen=True, slots=True)
class CacheInventory:
    """Complete cache-reader and invalidation inventory for scanned roots."""

    cached_functions: tuple[CachedFunction, ...]
    invalidation_calls: tuple[InvalidationCall, ...]

    @property
    def legacy_cached_count(self) -> int:
        """Return readers still using the legacy non-generation decorator."""
        return sum(item.cache_kind == "cached" for item in self.cached_functions)

    @property
    def generation_cached_count(self) -> int:
        """Return readers already using the bounded generation decorator."""
        return sum(item.cache_kind == "generation_cached" for item in self.cached_functions)

    @property
    def unbounded_invalidation_count(self) -> int:
        """Return the number of production invalidations that can scan keyspace."""
        return sum(not call.bounded for call in self.invalidation_calls)

    @property
    def migration_complete(self) -> bool:
        """Return whether every remote cache path satisfies the bounded design."""
        return self.legacy_cached_count == 0 and self.unbounded_invalidation_count == 0


class _InventoryVisitor(ast.NodeVisitor):
    """Collect cache decorators and invalidation calls from one Python module."""

    def __init__(self, path: Path) -> None:
        self.path = path.as_posix()
        self.function_stack: list[str] = []
        self.cached_functions: list[CachedFunction] = []
        self.invalidation_calls: list[InvalidationCall] = []

    @staticmethod
    def _call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.function_stack.append(node.name)
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            name = self._call_name(target)
            if name in _CACHE_DECORATORS:
                self.cached_functions.append(
                    CachedFunction(
                        path=self.path,
                        line=node.lineno,
                        function=node.name,
                        cache_kind=name,
                    )
                )
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit a synchronous function."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit an asynchronous function."""
        self._visit_function(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Record cache invalidation calls."""
        name = self._call_name(node.func)
        if name in _INVALIDATION_CALLS:
            self.invalidation_calls.append(
                InvalidationCall(
                    path=self.path,
                    line=node.lineno,
                    function=self.function_stack[-1] if self.function_stack else "<module>",
                    invalidation_kind=name,
                    bounded=name not in _UNBOUNDED_INVALIDATIONS,
                )
            )
        self.generic_visit(node)


def build_inventory(roots: tuple[Path, ...] = _DEFAULT_ROOTS) -> CacheInventory:
    """Scan Python source roots and return a deterministic cache inventory.

    Args:
        roots: Source directories to inspect recursively.

    Returns:
        Sorted cache reader and invalidation call inventory.
    """
    cached_functions: list[CachedFunction] = []
    invalidation_calls: list[InvalidationCall] = []

    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            visitor = _InventoryVisitor(path)
            visitor.visit(tree)
            cached_functions.extend(visitor.cached_functions)
            invalidation_calls.extend(visitor.invalidation_calls)

    cached_functions.sort(key=lambda item: (item.path, item.line, item.function))
    invalidation_calls.sort(key=lambda item: (item.path, item.line, item.function))
    return CacheInventory(tuple(cached_functions), tuple(invalidation_calls))


def _render_text(inventory: CacheInventory) -> str:
    lines = [
        "Cached functions:",
        *(
            f"  {item.path}:{item.line} {item.function} [{item.cache_kind}]"
            for item in inventory.cached_functions
        ),
        "Invalidation calls:",
        *(
            f"  {item.path}:{item.line} {item.function} "
            f"[{item.invalidation_kind}; {'bounded' if item.bounded else 'UNBOUNDED'}]"
            for item in inventory.invalidation_calls
        ),
        f"Legacy cached readers: {inventory.legacy_cached_count}",
        f"Generation cached readers: {inventory.generation_cached_count}",
        f"Unbounded invalidation calls: {inventory.unbounded_invalidation_count}",
        f"Bounded migration complete: {'yes' if inventory.migration_complete else 'no'}",
    ]
    return "\n".join(lines)


def main() -> int:
    """Run the cache inventory CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero while legacy readers or unbounded invalidations remain",
    )
    args = parser.parse_args()

    inventory = build_inventory()
    if args.json:
        print(
            json.dumps(
                {
                    "cached_functions": [asdict(item) for item in inventory.cached_functions],
                    "invalidation_calls": [asdict(item) for item in inventory.invalidation_calls],
                    "legacy_cached_count": inventory.legacy_cached_count,
                    "generation_cached_count": inventory.generation_cached_count,
                    "unbounded_invalidation_count": inventory.unbounded_invalidation_count,
                    "migration_complete": inventory.migration_complete,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_render_text(inventory))

    if args.check and not inventory.migration_complete:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
