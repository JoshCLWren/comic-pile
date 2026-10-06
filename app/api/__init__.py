"""API route handlers.

This package intentionally imports nothing. Cold serverless starts serve
``/api/ping`` without paying for the whole API import graph, so every router
submodule is imported by the registration function that needs it (see
``app.main.register_all_routers`` and ``app.api.dependency.mount_subrouters``).

Import a router submodule explicitly (``from app.api import thread``) instead of
relying on package-attribute access, which this package no longer provides.
"""

#: Router submodules this package composes during application registration.
#: Listed for discoverability only: the names are not bound as attributes of
#: this package, so ``from app.api import *`` does not resolve them.
ROUTER_SUBMODULES = (
    "analytics",
    "cbl_sources",
    "comicvine_resolution",
    "continuity_plan",
    "continuity_rule",
    "continuity_template",
    "custom_cbl",
    "dependency",
    "dependency_group",
    "dependency_group_batch",
    "health",
    "issue_dependency_batch",
    "reading_order_projection",
    "recommendation_diagnostics",
    "releases",
    "roll_recovery_switch",
    "taste_signal",
)