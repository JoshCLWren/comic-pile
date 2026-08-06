"""Regression coverage for credential-safe application startup logging."""

import ast
from pathlib import Path


def test_main_uses_allowlisted_database_metadata_for_startup_logging() -> None:
    """Application startup must not render a connection URL into a log message."""
    source = Path("app/main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "safe_connection_metadata" in imported_names
    assert "safe_connection_metadata" in called_names
    assert "make_url" not in imported_names
    assert "render_as_string" not in called_attributes
    assert "Starting with DATABASE_URL" not in source
