"""Focused regressions for the generated native v2 request client."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_native_client import (
    CLIENT_OUTPUT,
    NATIVE_CONTRACT,
    UNIFIED_SCHEMA,
    NativeClientGenerationError,
    _method_name,
    load_json,
    render_native_client,
)

ROOT = Path(__file__).resolve().parents[1]


def _operation(
    operation_id: str,
    *,
    parameters: list[dict[str, object]] | None = None,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one minimal merged operation declaration."""
    operation: dict[str, object] = {
        "operationId": operation_id,
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Result"}
                    }
                }
            }
        },
    }
    if parameters is not None:
        operation["parameters"] = parameters
    if body is not None:
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/Body"}}
            },
        }
    return operation


def test_render_native_client_is_deterministic() -> None:
    """Render the same contracts to byte-identical client source."""
    native: dict[str, object] = {
        "paths": {
            "/api/v2/widgets": {
                "get": {
                    "operationId": "list_widgets_documentation",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Result"}
                                }
                            }
                        }
                    },
                }
            }
        }
    }
    unified: dict[str, object] = {
        "paths": {
            "/api/v2/widgets": {
                "get": {
                    "operationId": "list_widgets_documentation",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Result"}
                                }
                            }
                        }
                    },
                }
            }
        }
    }

    first = render_native_client(unified, native)
    second = render_native_client(unified, native)

    assert first == second
    assert first.endswith("\n")
    assert not first.endswith("\n\n")


def test_render_native_client_uses_generated_paths_query_and_body_types() -> None:
    """Derive delegation, path encoding, query compaction and body typing."""
    native: dict[str, object] = {
        "paths": {
            "/api/v2/widgets/{widget_id}": {
                "patch": _operation(
                    "update_widget_documentation",
                    parameters=[
                        {
                            "in": "path",
                            "name": "widget_id",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    body={},
                )
            },
            "/api/v2/widgets": {
                "get": _operation(
                    "list_widgets_documentation",
                    parameters=[
                        {
                            "in": "query",
                            "name": "search",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "in": "query",
                            "name": "page_size",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                )
            },
        }
    }
    unified: dict[str, object] = {
        "paths": {
            "/api/v2/widgets/{widget_id}": {
                "patch": _operation(
                    "update_widget_documentation",
                    parameters=[
                        {
                            "in": "path",
                            "name": "widget_id",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    body={},
                )
            },
            "/api/v2/widgets": {
                "get": _operation(
                    "list_widgets_documentation",
                    parameters=[
                        {
                            "in": "query",
                            "name": "search",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "in": "query",
                            "name": "page_size",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                )
            },
        }
    }

    rendered = render_native_client(unified, native)

    assert "export interface UpdateWidgetRequest {" in rendered
    assert "body: components['schemas']['Body']" in rendered
    assert "export type UpdateWidgetResponse = components['schemas']['Result']" in rendered
    assert (
        "client.patch<UpdateWidgetResponse, UpdateWidgetRequest['body']>("
        in rendered
    )
    assert (
        "`/v2/widgets/${encodeURIComponent(String(args.path.widget_id))}`"
        in rendered
    )
    assert "export interface ListWidgetsRequest {" in rendered
    assert "query?: {" in rendered
    assert "search?: string" in rendered
    assert "page_size?: number" in rendered
    assert "client.get<ListWidgetsResponse>(" in rendered
    assert "{ params: compactQuery(args.query) }" in rendered
    assert "listWidgets(args?: ListWidgetsRequest)" in rendered
    assert "fetch(" not in rendered
    assert "from 'axios'" not in rendered


def test_render_native_client_keeps_required_query_group_required() -> None:
    """A required query parameter forces the argument group to be present."""
    operation = _operation(
        "search_widgets_documentation",
        parameters=[
            {
                "in": "query",
                "name": "term",
                "required": True,
                "schema": {"type": "string"},
            },
            {
                "in": "query",
                "name": "page_token",
                "required": False,
                "schema": {"type": "string"},
            },
        ],
    )
    rendered = render_native_client(
        {"paths": {"/api/v2/widgets": {"get": operation}}},
        {"paths": {"/api/v2/widgets": {"get": operation}}},
    )

    assert "term: string" in rendered
    assert "page_token?: string" in rendered
    assert "searchWidgets(args: SearchWidgetsRequest)" in rendered


def test_render_native_client_rejects_missing_merged_operation() -> None:
    """Fail closed when the native contract is absent from the merged schema."""
    with pytest.raises(NativeClientGenerationError, match="missing"):
        render_native_client(
            {"paths": {}},
            {"paths": {"/api/v2/widgets": {"get": _operation("list_widgets_documentation")}}},
        )


def test_render_native_client_rejects_duplicate_method_names() -> None:
    """Reject two native operations that collapse to the same client method."""
    operation = _operation("same_documentation")
    with pytest.raises(NativeClientGenerationError, match="duplicate"):
        render_native_client(
            {
                "paths": {
                    "/api/v2/one": {"get": operation},
                    "/api/v2/two": {"get": operation},
                }
            },
            {
                "paths": {
                    "/api/v2/one": {"get": operation},
                    "/api/v2/two": {"get": operation},
                }
            },
        )


def test_checked_in_native_client_covers_every_native_operation() -> None:
    """The checked-in client derives a method for every deployed native operation."""
    native = load_json(ROOT / NATIVE_CONTRACT)
    rendered = (ROOT / CLIENT_OUTPUT).read_text(encoding="utf-8")
    paths = native.get("paths")
    assert isinstance(paths, dict)
    for raw_item in paths.values():
        assert isinstance(raw_item, dict)
        for raw_operation in raw_item.values():
            assert isinstance(raw_operation, dict)
            operation_id = raw_operation.get("operationId")
            assert isinstance(operation_id, str)
            assert f"  {_method_name(operation_id)}(" in rendered


def test_checked_in_native_client_is_current() -> None:
    """Fail when the checked-in request client drifts from the contracts."""
    rendered = render_native_client(
        load_json(ROOT / UNIFIED_SCHEMA),
        load_json(ROOT / NATIVE_CONTRACT),
    )

    assert (ROOT / CLIENT_OUTPUT).read_text(encoding="utf-8") == rendered
