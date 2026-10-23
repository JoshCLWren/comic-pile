"""Service for bootstrap alias telemetry.

Handles the retrieval and formatting of process-local alias counters for
observability of the legacy-route deletion gate.
"""

from app.bootstrap_route_telemetry import bootstrap_alias_snapshot
from app.schemas.bootstrap_telemetry import (
    BootstrapAliasCounterSchema,
    BootstrapAliasSnapshotSchema,
)


def get_bootstrap_alias_snapshot() -> BootstrapAliasSnapshotSchema:
    """Retrieve and format the current bootstrap alias counters.

    Returns:
        A snapshot schema containing deterministic aggregated counters.
    """
    counters = bootstrap_alias_snapshot()
    schema_counters = [
        BootstrapAliasCounterSchema(
            alias=c.alias,
            web_origin=c.web_origin,
            status_class=c.status_class,
            count=c.count,
        )
        for c in counters
    ]
    return BootstrapAliasSnapshotSchema(counters=schema_counters)
