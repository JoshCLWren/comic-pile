"""Regression tests for deterministic OpenAPI schema generation."""

from pathlib import Path

from scripts.export_openapi_schema import (
    is_client_schema_path,
    prune_legacy_bare_paths,
    render_openapi_schema,
    write_schema,
)


def test_render_openapi_schema_is_stable_and_newline_terminated() -> None:
    """Sort nested keys and emit exactly one trailing newline."""
    schema = {
        "paths": {"/z": {"get": {}}, "/a": {"post": {}}},
        "info": {"version": "1", "title": "ComicPile"},
    }

    rendered = render_openapi_schema(schema)

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")
    assert rendered.index('"info"') < rendered.index('"paths"')
    assert rendered.index('"/a"') < rendered.index('"/z"')


def test_write_schema_creates_parent_directory_and_file(tmp_path: Path) -> None:
    """Create a missing generated directory and write the rendered schema."""
    output = tmp_path / "generated" / "openapi.json"

    assert write_schema(output, '{"openapi":"3.1.0"}\n', check=False)
    assert output.read_text(encoding="utf-8") == '{"openapi":"3.1.0"}\n'


def test_check_mode_accepts_current_output_without_rewriting(tmp_path: Path) -> None:
    """Return success when checked-in output exactly matches generation."""
    output = tmp_path / "openapi.json"
    output.write_text("current\n", encoding="utf-8")
    original_mtime = output.stat().st_mtime_ns

    assert write_schema(output, "current\n", check=True)
    assert output.stat().st_mtime_ns == original_mtime


def test_check_mode_rejects_missing_or_stale_output(tmp_path: Path) -> None:
    """Reject absent and changed generated schemas without modifying them."""
    output = tmp_path / "openapi.json"

    assert not write_schema(output, "current\n", check=True)

    output.write_text("stale\n", encoding="utf-8")
    assert not write_schema(output, "current\n", check=True)
    assert output.read_text(encoding="utf-8") == "stale\n"


def test_is_client_schema_path_keeps_infra_v1_and_ping_only() -> None:
    """Classify infrastructure paths, canonical v1 routes, and ping as client."""
    assert is_client_schema_path("/")
    assert is_client_schema_path("/health")
    assert is_client_schema_path("/{full_path}")
    assert is_client_schema_path("/api/ping")
    assert is_client_schema_path("/api/v1")
    assert is_client_schema_path("/api/v1/threads/")

    assert not is_client_schema_path("/api/threads/")
    assert not is_client_schema_path("/api/metrics")
    assert not is_client_schema_path("/api/v10/threads")


def test_prune_legacy_bare_paths_drops_aliases_and_tooling() -> None:
    """Drop legacy bare aliases while keeping v1 routes, ping, and infra."""
    schema = {
        "openapi": "3.1.0",
        "paths": {
            "/health": {"get": {}},
            "/api/ping": {"get": {}},
            "/api/v1/threads/": {"get": {}},
            "/api/threads/": {"get": {}},
            "/api/debug/log": {"post": {}},
        },
    }

    pruned = prune_legacy_bare_paths(schema)

    assert sorted(pruned["paths"]) == ["/api/ping", "/api/v1/threads/", "/health"]
    assert sorted(schema["paths"]) == [
        "/api/debug/log",
        "/api/ping",
        "/api/threads/",
        "/api/v1/threads/",
        "/health",
    ]


def test_prune_legacy_bare_paths_returns_original_when_fully_client_facing() -> None:
    """Return the input document unchanged when no path requires pruning."""
    schema = {"paths": {"/api/v1/roll/": {"post": {}}, "/api/ping": {"get": {}}}}

    assert prune_legacy_bare_paths(schema) is schema


def test_prune_legacy_bare_paths_tolerates_missing_paths_mapping() -> None:
    """Pass documents without a paths mapping through untouched."""
    schema = {"info": {"title": "ComicPile"}}

    assert prune_legacy_bare_paths(schema) is schema
