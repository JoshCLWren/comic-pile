"""Shared wire-contract constants for undo snapshot payloads."""

SNAPSHOT_VERSION_KEY = "_version"
SNAPSHOT_VERSION = 2
QUEUE_CHANGES_KEY = "_queue_changes"
BLOCKED_CHANGES_KEY = "_blocked_changes"
USES_ISSUE_TRACKING_KEY = "uses_issue_tracking"

# Queryable snapshot classification (issue #3218). Writers and the additive
# backfill migration derive these from the real payload contract so the latest
# delta can be selected with SQL filtering instead of loading the stack.
SNAPSHOT_KIND_DELTA = "delta"
SNAPSHOT_KIND_SESSION_START = "session_start"
SNAPSHOT_KIND_LEGACY_FULL = "legacy_full"
SNAPSHOT_KIND_UNKNOWN = "unknown"

SESSION_START_DESCRIPTION = "Session start"

# Upper bound on payload rows inspected by the legacy compatibility fallback.
# Post-backfill every row is classified, so this only covers rows written by
# pre-migration code during the rollout window.
LEGACY_DELTA_FALLBACK_SCAN_LIMIT = 500


def classify_snapshot(
    thread_states: object,
    *,
    description: str | None = None,
    event_id: int | None = None,
) -> tuple[str, int | None]:
    """Derive queryable (kind, schema version) metadata from a snapshot payload.

    The classification mirrors the supported undo contract exactly: a payload
    is a consumable delta only when its ``_version`` equals
    :data:`SNAPSHOT_VERSION`. Versioned but unsupported payloads stay
    classified as delta rows with their own version so they remain queryable
    without becoming undo targets. Session-start checkpoints keep their
    ``event_id IS NULL`` plus description identity. Anything else is a legacy
    full-library snapshot, or unknown when the payload is not a JSON object.

    Args:
        thread_states: Raw snapshot payload. Non-dict (malformed) payloads
            classify as unknown without raising.
        description: Snapshot description, if any.
        event_id: Linked event ID, if any.

    Returns:
        Tuple of snapshot kind and schema version (None when unversioned).
    """
    version: object = None
    if isinstance(thread_states, dict):
        version = thread_states.get(SNAPSHOT_VERSION_KEY)
    if isinstance(version, bool):
        version = None
    elif isinstance(version, float):
        version = int(version) if version.is_integer() else None
    if isinstance(version, int):
        return SNAPSHOT_KIND_DELTA, version
    if not isinstance(thread_states, dict):
        return SNAPSHOT_KIND_UNKNOWN, None
    if description == SESSION_START_DESCRIPTION and event_id is None:
        return SNAPSHOT_KIND_SESSION_START, None
    return SNAPSHOT_KIND_LEGACY_FULL, None
