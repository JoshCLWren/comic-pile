#!/usr/bin/env python3
"""Generate the thin TypeScript request client for deployed native v2 operations.

The client is derived from two checked-in generated artifacts:

* ``native/contracts/v2-runtime.openapi.json`` selects the exact deployed native
  operations (and will naturally include future native additions), and
* ``frontend/src/generated/openapi.json`` supplies the merged operation types and
  component-schema names that ``openapi.ts`` already exports.

The generated factory delegates every request to the caller-provided
``HttpClient``, so authentication, CSRF, retries, and error handling stay in the
existing transport. Paths, query parameters, bodies, and success response types
come from the contracts rather than a hand-maintained per-operation table.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Final

NATIVE_CONTRACT: Final = Path("native/contracts/v2-runtime.openapi.json")
UNIFIED_SCHEMA: Final = Path("frontend/src/generated/openapi.json")
CLIENT_OUTPUT: Final = Path("frontend/src/generated/nativeV2Client.ts")

API_BASE_PREFIX: Final = "/api"
REF_PREFIX: Final = "#/components/schemas/"
JSON_MEDIA_TYPE: Final = "application/json"
SUPPORTED_METHODS: Final = frozenset({"get", "post", "put", "patch", "delete"})
_IDENTIFIER: Final = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


class NativeClientGenerationError(ValueError):
    """Raised when the contracts cannot produce a deterministic client."""


@dataclass(frozen=True)
class RequestField:
    """One generated request argument group."""

    name: str
    optional: bool
    type_text: str | None
    nested: tuple[tuple[str, bool, str], ...] = ()


@dataclass(frozen=True)
class Operation:
    """One native v2 operation rendered into the generated client."""

    method: str
    path: str
    operation_id: str
    name: str
    request_name: str | None
    response_name: str
    request_fields: tuple[RequestField, ...]
    response_type: str
    path_parameters: tuple[str, ...]
    has_query: bool
    has_body: bool

    @property
    def has_required_input(self) -> bool:
        """Whether a caller must pass the request argument group."""
        return any(not field.optional for field in self.request_fields)


def load_json(path: Path) -> dict[str, object]:
    """Load a JSON object from ``path``.

    Args:
        path: JSON file to load.

    Returns:
        A string-keyed object mapping.
    """
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise NativeClientGenerationError(f"{path} must contain a JSON object")
    return {str(key): item for key, item in value.items()}


def _object(value: object, context: str) -> dict[str, object]:
    """Narrow ``value`` to a string-keyed JSON object."""
    if not isinstance(value, dict):
        raise NativeClientGenerationError(f"{context} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _literal(value: object) -> str:
    """Render one JSON scalar as a TypeScript literal type."""
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return "unknown"


def _primitive_type(name: str) -> str:
    """Map one OpenAPI scalar type name to TypeScript."""
    mapping = {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
        "object": "Record<string, unknown>",
        "array": "Array<unknown>",
    }
    return mapping.get(name, "unknown")


def _property_name(name: str) -> str:
    """Render an object property name, quoting only when necessary."""
    return name if _IDENTIFIER.fullmatch(name) else json.dumps(name)


def _typed_schema(schema: dict[str, object], type_name: str) -> str:
    """Render one non-reference schema body."""
    if type_name == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            return f"Array<{_ts_type(_object(items, 'items'))}>"
        return "Array<unknown>"
    if type_name == "object":
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            required_raw = schema.get("required")
            required = {
                item for item in required_raw if isinstance(item, str)
            } if isinstance(required_raw, list) else set()
            fields = [
                f"{_property_name(name)}{'' if name in required else '?'}: "
                f"{_ts_type(_object(property_schema, f'property {name}'))}"
                for name, property_schema in _object(
                    properties, "properties"
                ).items()
            ]
            return "{ " + "; ".join(fields) + " }"
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            return (
                "Record<string, "
                f"{_ts_type(_object(additional, 'additionalProperties'))}>"
            )
        return "Record<string, unknown>"
    return _primitive_type(type_name)


def _ts_type(schema: dict[str, object]) -> str:
    """Render an OpenAPI schema fragment as a TypeScript type."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        if not ref.startswith(REF_PREFIX):
            raise NativeClientGenerationError(f"unsupported external reference {ref!r}")
        return f"components['schemas']['{ref[len(REF_PREFIX):]}']"

    for combinator in ("anyOf", "oneOf"):
        variants = schema.get(combinator)
        if isinstance(variants, list):
            parts = [
                _ts_type(_object(variant, combinator)) for variant in variants
            ]
            unique = list(dict.fromkeys(parts))
            return " | ".join(unique) if unique else "unknown"

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        parts = [_ts_type(_object(variant, "allOf")) for variant in all_of]
        unique = list(dict.fromkeys(parts))
        return " & ".join(unique) if unique else "unknown"

    if "const" in schema:
        return _literal(schema.get("const"))

    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return " | ".join(dict.fromkeys(_literal(value) for value in enum))

    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        parts = [
            _primitive_type(name) for name in raw_type if isinstance(name, str)
        ]
        unique = list(dict.fromkeys(parts))
        return " | ".join(unique) if unique else "unknown"
    if isinstance(raw_type, str):
        return _typed_schema(schema, raw_type)
    if isinstance(schema.get("properties"), dict):
        return _typed_schema(schema, "object")
    if "items" in schema:
        return _typed_schema(schema, "array")
    return "unknown"


def _method_name(operation_id: str) -> str:
    """Derive one stable camelCase method name from a generated operation id."""
    base = operation_id.removesuffix("_documentation")
    words = [word for word in base.split("_") if word]
    if not words:
        raise NativeClientGenerationError(
            f"operation id {operation_id!r} has no usable method name"
        )
    return words[0] + "".join(word[:1].upper() + word[1:] for word in words[1:])


def _pascal_case(name: str) -> str:
    """Capitalize a generated method name for its exported type names."""
    return name[:1].upper() + name[1:]


def _success_response_type(operation: dict[str, object]) -> str:
    """Render the lowest 2xx JSON response schema, or ``void``."""
    responses = _object(operation.get("responses"), "responses")
    success_codes = sorted(
        int(code)
        for code in responses
        if code.isdigit() and 200 <= int(code) < 300
    )
    if not success_codes:
        return "void"
    response = _object(responses[str(success_codes[0])], "success response")
    content = response.get("content")
    if not isinstance(content, dict):
        return "void"
    media = content.get(JSON_MEDIA_TYPE)
    if not isinstance(media, dict):
        return "void"
    schema = media.get("schema")
    if not isinstance(schema, dict):
        return "void"
    return _ts_type(_object(schema, "response schema"))


def _json_body_schema(request_body: dict[str, object]) -> dict[str, object]:
    """Return the application/json request-body schema."""
    content = _object(request_body.get("content"), "requestBody.content")
    media = content.get(JSON_MEDIA_TYPE)
    if not isinstance(media, dict):
        raise NativeClientGenerationError(
            "request body does not declare application/json content"
        )
    return _object(media.get("schema"), "requestBody schema")


def _build_operation(
    method: str,
    path: str,
    operation: dict[str, object],
) -> Operation:
    """Build one rendered operation from its merged OpenAPI declaration."""
    if method not in SUPPORTED_METHODS:
        raise NativeClientGenerationError(
            f"unsupported native method {method!r} for {path}"
        )
    raw_operation_id = operation.get("operationId")
    if not isinstance(raw_operation_id, str) or not raw_operation_id:
        raise NativeClientGenerationError(
            f"{method.upper()} {path} has no generated operationId"
        )
    name = _method_name(raw_operation_id)

    path_fields: list[tuple[str, bool, str]] = []
    query_fields: list[tuple[str, bool, str]] = []
    path_parameters: list[str] = []
    raw_parameters = operation.get("parameters")
    if isinstance(raw_parameters, list):
        for raw_parameter in raw_parameters:
            parameter = _object(raw_parameter, "parameter")
            location = parameter.get("in")
            parameter_name = parameter.get("name")
            if not isinstance(parameter_name, str) or not parameter_name:
                raise NativeClientGenerationError("parameter has no name")
            schema = _object(parameter.get("schema", {}), "parameter schema")
            type_text = _ts_type(schema)
            if location == "path":
                path_fields.append((parameter_name, False, type_text))
                path_parameters.append(parameter_name)
            elif location == "query":
                required = parameter.get("required") is True
                query_fields.append((parameter_name, not required, type_text))
            else:
                raise NativeClientGenerationError(
                    f"{method.upper()} {path} has unsupported parameter "
                    f"location {location!r}"
                )

    fields: list[RequestField] = []
    if path_fields:
        fields.append(
            RequestField(name="path", optional=False, type_text=None, nested=tuple(path_fields))
        )
    if query_fields:
        fields.append(
            RequestField(
                name="query",
                optional=all(optional for _, optional, _ in query_fields),
                type_text=None,
                nested=tuple(query_fields),
            )
        )

    has_body = False
    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        body_schema = _json_body_schema(request_body)
        body_required = request_body.get("required") is True
        fields.append(
            RequestField(
                name="body",
                optional=not body_required,
                type_text=_ts_type(body_schema),
            )
        )
        has_body = True

    request_name = f"{_pascal_case(name)}Request" if fields else None
    return Operation(
        method=method,
        path=path,
        operation_id=raw_operation_id,
        name=name,
        request_name=request_name,
        response_name=f"{_pascal_case(name)}Response",
        request_fields=tuple(fields),
        response_type=_success_response_type(operation),
        path_parameters=tuple(path_parameters),
        has_query=bool(query_fields),
        has_body=has_body,
    )


def _native_operations(native: dict[str, object]) -> list[tuple[str, str]]:
    """List the deployed native operations as sorted ``(method, path)`` pairs."""
    paths = _object(native.get("paths"), "native paths")
    operations: list[tuple[str, str]] = []
    for path, raw_item in paths.items():
        item = _object(raw_item, f"native path {path}")
        for method in item:
            operations.append((method.lower(), path))
    return sorted(set(operations))


def _render_request_type(operation: Operation) -> list[str]:
    """Render one exported request interface."""
    if operation.request_name is None:
        return []
    lines = [f"export interface {operation.request_name} {{"]
    for field in operation.request_fields:
        optional = "?" if field.optional else ""
        if field.type_text is not None:
            lines.append(f"  {field.name}{optional}: {field.type_text}")
            continue
        lines.append(f"  {field.name}{optional}: {{")
        for name, nested_optional, type_text in field.nested:
            nested = "?" if nested_optional else ""
            lines.append(f"    {name}{nested}: {type_text}")
        lines.append("  }")
    lines.append("}")
    return lines


def _path_expression(name: str) -> str:
    """Render a path-parameter access expression for generated code."""
    if _IDENTIFIER.fullmatch(name):
        return f"args.path.{name}"
    return f"args.path[{json.dumps(name)}]"


def _render_url(operation: Operation) -> str:
    """Render the base-relative URL expression for one operation."""
    if not operation.path.startswith(f"{API_BASE_PREFIX}/"):
        raise NativeClientGenerationError(
            f"native path {operation.path!r} is not under {API_BASE_PREFIX}/"
        )
    path = operation.path[len(API_BASE_PREFIX):]
    if not operation.path_parameters:
        return json.dumps(path)
    for name in operation.path_parameters:
        path = path.replace(
            "{" + name + "}",
            "${encodeURIComponent(String(" + _path_expression(name) + "))}",
        )
    if re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", path):
        raise NativeClientGenerationError(
            f"native path {operation.path!r} has an undeclared path parameter"
        )
    return f"`{path}`"


def _render_call(operation: Operation) -> list[str]:
    """Render the delegated HttpClient call for one operation."""
    url = _render_url(operation)
    response = operation.response_name
    if operation.method in {"get", "delete"}:
        if not operation.has_query:
            if not operation.path_parameters:
                return [f"      return client.{operation.method}<{response}>({url})"]
            return [
                f"      return client.{operation.method}<{response}>(",
                f"        {url},",
                "      )",
            ]
        return [
            f"      return client.{operation.method}<{response}>(",
            f"        {url},",
            "        { params: compactQuery(args.query) },",
            "      )",
        ]
    if operation.has_body and operation.request_name is not None:
        return [
            f"      return client.{operation.method}<{response}, "
            f"{operation.request_name}['body']>(",
            f"        {url},",
            "        args.body,",
            "      )",
        ]
    return [f"      return client.{operation.method}<{response}>({url})"]


def _render_method_signature(operation: Operation) -> str:
    """Render the interface method signature for one operation."""
    if operation.request_name is None:
        return f"  {operation.name}(): Promise<{operation.response_name}>"
    optional = "?" if not operation.has_required_input else ""
    return (
        f"  {operation.name}(args{optional}: {operation.request_name}): "
        f"Promise<{operation.response_name}>"
    )


def _render_implementation(operation: Operation) -> list[str]:
    """Render the factory method implementation for one operation."""
    if operation.request_name is None:
        lines = [f"    {operation.name}() {{"]
    elif operation.has_required_input:
        lines = [f"    {operation.name}(args: {operation.request_name}) {{"]
    else:
        lines = [f"    {operation.name}(args: {operation.request_name} = {{}}) {{"]
    lines.extend(_render_call(operation))
    lines.append("    },")
    return lines


def render_native_client(
    unified_schema: dict[str, object],
    native_contract: dict[str, object],
) -> str:
    """Render the checked-in native v2 request client.

    Args:
        unified_schema: Merged generated OpenAPI document.
        native_contract: Canonical Rust-generated native v2 contract.

    Returns:
        Deterministic TypeScript source ending in one newline.

    Raises:
        NativeClientGenerationError: When a native operation is missing from the
            unified schema, an operation id is unusable, or two operations would
            generate the same method name.
    """
    unified_paths = _object(unified_schema.get("paths"), "merged paths")
    operations: list[Operation] = []
    for method, path in _native_operations(native_contract):
        raw_path_item = unified_paths.get(path)
        if not isinstance(raw_path_item, dict):
            raise NativeClientGenerationError(
                f"native operation {method.upper()} {path} is missing from the "
                "merged generated schema"
            )
        path_item = _object(raw_path_item, f"merged path {path}")
        raw_operation = path_item.get(method)
        if not isinstance(raw_operation, dict):
            raise NativeClientGenerationError(
                f"native operation {method.upper()} {path} is missing from the "
                "merged generated schema"
            )
        operations.append(
            _build_operation(method, path, _object(raw_operation, f"{method} {path}"))
        )

    operations.sort(key=lambda operation: operation.name)
    names = [operation.name for operation in operations]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise NativeClientGenerationError(
            f"duplicate generated method names: {duplicates}"
        )

    lines = [
        "// Generated by scripts/generate_native_client.py from",
        "// native/contracts/v2-runtime.openapi.json and",
        "// frontend/src/generated/openapi.json. Do not edit by hand.",
        "// Regenerate with `python scripts/generate_openapi_types.py`.",
        "",
        "import type { HttpClient } from '../services/httpClient'",
        "import type { components } from './openapi'",
        "",
        "/**",
        " * Drop absent optional query values before the transport serializes them.",
        " *",
        " * @param query - Optional generated query argument group.",
        " * @returns The present values, or `undefined` when nothing remains.",
        " */",
        "export function compactQuery(",
        "  query: object | undefined,",
        "): Record<string, unknown> | undefined {",
        "  if (!query) return undefined",
        "  const params: Record<string, unknown> = {}",
        "  for (const [key, value] of Object.entries(query)) {",
        "    if (value !== undefined && value !== null) params[key] = value",
        "  }",
        "  return Object.keys(params).length > 0 ? params : undefined",
        "}",
        "",
    ]

    for operation in operations:
        lines.extend(_render_request_type(operation))
        if operation.request_name is not None:
            lines.append("")
        lines.append(
            f"export type {operation.response_name} = {operation.response_type}"
        )
        lines.append("")

    lines.append("export interface NativeV2Client {")
    lines.extend(_render_method_signature(operation) for operation in operations)
    lines.append("}")
    lines.append("")
    lines.append(
        "export function createNativeV2Client(client: HttpClient): NativeV2Client {"
    )
    lines.append("  return {")
    for operation in operations:
        lines.extend(_render_implementation(operation))
    lines.append("  }")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def generate_native_client(
    schema_path: Path,
    native_path: Path,
    output: Path,
) -> None:
    """Render and write the native v2 request client.

    Args:
        schema_path: Merged generated OpenAPI document.
        native_path: Canonical native v2 contract.
        output: TypeScript client destination.
    """
    rendered = render_native_client(load_json(schema_path), load_json(native_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=UNIFIED_SCHEMA)
    parser.add_argument("--native", type=Path, default=NATIVE_CONTRACT)
    parser.add_argument("--output", type=Path, default=CLIENT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the checked-in client differs instead of rewriting it",
    )
    return parser.parse_args()


def main() -> int:
    """Generate or verify the native v2 request client."""
    args = _parse_args()
    rendered = render_native_client(
        load_json(args.schema), load_json(args.native)
    )
    if args.check:
        if args.output.exists() and args.output.read_text(encoding="utf-8") == rendered:
            print(f"Verified generated native v2 client: {args.output}")
            return 0
        print(
            f"Generated native v2 client is stale: {args.output}\n"
            "Run `python scripts/generate_openapi_types.py` and commit the result."
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote generated native v2 client: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
