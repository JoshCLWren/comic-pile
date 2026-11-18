"""Retired Python handlers for issue-identity CBL lookup/compare/candidates (#4843).

These same-path operations are served by the native Rust router. The module and
router remain importable because other Python composition code still includes
them, but no Python handlers are registered here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/issue-identity", tags=["issue-identity"])

