"""Shared pytest fixtures."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_file(tmp_path: Path):
    """Provide a temporary file path."""
    return tmp_path / "test.txt"
