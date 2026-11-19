"""Thread CRUD API endpoints.

Retired: all thread HTTP routes are now served natively by Rust (#4832).
This module is retained as an empty shell so deferred cold-start imports and
lazy-router tests keep resolving; it registers no routes.
"""

from fastapi import APIRouter

router = APIRouter(tags=["threads"])

#: Versioned-only router retained for cold-start import compatibility. Registers
#: no routes; native Rust serves every thread operation.
v1_router = APIRouter(tags=["threads"])