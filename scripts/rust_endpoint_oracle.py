#!/usr/bin/env python3
"""Freeze an existing OpenAPI operation and record its parameterized ORM SQL.

The native implementation must supply its own generated OpenAPI document to
``check``. Comparing the Python document with itself is not native verification.
SQL transcripts contain parameter types and transaction events, never values.
"""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path


def _mapping(value: object) -> dict[str, object]:
    """Require a JSON object with string keys."""
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("Expected a JSON object")
    return value.copy()


def _refs(value: object) -> set[str]:
    """Collect local component references recursively, including array items."""
    if isinstance(value, dict):
        found = set()
        ref = value.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith("#/components/"):
                raise ValueError(f"Unsupported non-component reference: {ref}")
            found.add(ref)
        for item in value.values():
            found.update(_refs(item))
        return found
    if isinstance(value, list):
        return set().union(*(_refs(item) for item in value))
    return set()


def operation_contract(schema: dict[str, object], path: str, method: str) -> dict[str, object]:
    """Extract one operation and the complete transitive component closure.

    Preserve path-level parameters and effective root security, not just the
    response model. Missing references fail closed rather than losing fields.
    """
    paths = _mapping(schema["paths"])
    path_item = _mapping(paths[path])
    operation = _mapping(path_item[method.lower()])
    if "security" not in operation and "security" in schema:
        operation["security"] = schema["security"]
    retained_path = {key: value for key, value in path_item.items() if key in {
        "parameters", "servers", "summary", "description",
    }}
    retained_path[method.lower()] = operation
    components = _mapping(schema.get("components", {}))
    pending = _refs(retained_path)
    security = operation.get("security", [])
    if not isinstance(security, list):
        raise ValueError("Security requirements must be an array")
    for requirement in security:
        for name in _mapping(requirement):
            pending.add(f"#/components/securitySchemes/{name}")
    selected: dict[str, dict[str, object]] = {}
    visited = set()
    while pending:
        ref = pending.pop()
        if ref in visited:
            continue
        visited.add(ref)
        parts = ref.split("/")
        if len(parts) != 4:
            raise ValueError(f"Unsupported component reference: {ref}")
        section, name = (part.replace("~1", "/").replace("~0", "~") for part in parts[2:])
        component = _mapping(components[section])[name]
        selected.setdefault(section, {})[name] = component
        pending.update(_refs(component) - visited)
    return {
        "openapi": schema["openapi"],
        "paths": {path: retained_path},
        "components": selected,
    }


def render(value: object) -> str:
    """Render stable JSON without reordering contract-sensitive arrays."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def parameter_shape(value: object) -> object:
    """Retain bind container shape and scalar type, never scalar values."""
    if isinstance(value, dict):
        return {str(key): parameter_shape(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [parameter_shape(item) for item in value]
    return type(value).__name__


class SqlTranscript:
    """SQLAlchemy event callbacks for a synthetic request's actual DB work.

    Attach to one test engine only; remove listeners in ``finally``. Do not
    attach to production or pass production records through this recorder.
    """

    def __init__(self) -> None:
        """Start a request-local transcript and connection numbering."""
        self.events: list[dict[str, object]] = []
        self._connections: dict[int, int] = {}

    def _connection(self, connection: object) -> int:
        key = id(connection)
        return self._connections.setdefault(key, len(self._connections) + 1)

    def statement(
        self, connection: object, cursor: object, statement: str,
        parameters: object, context: object, executemany: bool,
    ) -> None:
        """Record emitted PostgreSQL text plus redacted driver-bind shape."""
        compiled = getattr(context, "compiled", None)
        self.events.append({
            "event": "statement",
            "connection": self._connection(connection),
            "sql": statement,
            "bind_order": list(getattr(compiled, "positiontup", None) or []),
            "parameter_shape": parameter_shape(parameters),
            "executemany": executemany,
        })

    def begin(self, connection: object) -> None:
        """Record the real connection transaction start."""
        self.events.append({"event": "begin", "connection": self._connection(connection)})

    def commit(self, connection: object) -> None:
        """Record the real connection commit boundary."""
        self.events.append({"event": "commit", "connection": self._connection(connection)})

    def rollback(self, connection: object) -> None:
        """Record the real connection rollback boundary."""
        self.events.append({"event": "rollback", "connection": self._connection(connection)})


def main() -> int:
    """Freeze Python's schema or compare a separately generated native schema."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "check"])
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--path", default="/api/v1/roll/bootstrap")
    parser.add_argument("--method", default="get")
    args = parser.parse_args()
    schema = _mapping(json.loads(args.schema.read_text()))
    actual = render(operation_contract(schema, args.path, args.method))
    if args.command == "freeze":
        args.contract.parent.mkdir(parents=True, exist_ok=True)
        args.contract.write_text(actual)
        return 0
    expected = args.contract.read_text()
    if expected == actual:
        print(f"Operation matches frozen contract: {args.method.upper()} {args.path}")
        return 0
    print("".join(difflib.unified_diff(
        expected.splitlines(keepends=True), actual.splitlines(keepends=True),
        fromfile="frozen Python contract", tofile="generated candidate contract",
    )))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
