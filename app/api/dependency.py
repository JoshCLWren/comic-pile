"""Dependency API endpoints (/api/v1)."""

from fastapi import APIRouter


router = APIRouter(tags=["dependencies"])


#: True once :func:`mount_subrouters` has composed the dependency sub-routers into
#: :data:`router`. The router object is module-level state, so repeated
#: composition would append a second copy of every sub-route and shadow route
#: precedence with duplicates.
_subrouters_mounted = False


def mount_subrouters() -> None:
    """Compose the dependency sub-routers into :data:`router` exactly once.

    ``app/api/__init__.py`` deliberately performs no eager imports so a cold
    serverless start does not pay for the whole API surface. Composition moved
    here so the owning module owns the router it mutates.

    The sub-router modules are imported inside the function body on first call,
    so importing :mod:`app.api.dependency` alone stays cheap. Callers must
    invoke this before copying :data:`router` into an application, because
    ``FastAPI.include_router`` snapshots the included routes at call time.
    """
    global _subrouters_mounted
    if _subrouters_mounted:
        return

    from app.api import cbl_sources
    from app.api import dependency_group
    from app.api import reading_order_projection

    router.include_router(dependency_group.router)
    # project-preview is intentionally left on Python (out of scope for #4838).
    # The confirm/project operation is served by native Rust; its shadowed
    # Python handler has been removed from reading_order_projection.router.
    router.include_router(reading_order_projection.router)
    router.include_router(cbl_sources.router)

    _subrouters_mounted = True
