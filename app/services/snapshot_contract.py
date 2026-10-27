"""Shared wire-contract constants and payload types for undo snapshots."""

from typing import Final, NotRequired, TypedDict

SNAPSHOT_VERSION_KEY = "_version"
SNAPSHOT_VERSION = 2
QUEUE_CHANGES_KEY = "_queue_changes"
BLOCKED_CHANGES_KEY = "_blocked_changes"
USES_ISSUE_TRACKING_KEY: Final = "uses_issue_tracking"
# Compact per-action delta keys (issue #3226). A v2 rating delta stores only
# the records that actually changed on this action instead of repeating the
# rated thread's full issue collection.
ISSUE_CHANGES_KEY: Final = "issue_changes"
THREAD_CHANGES_KEY = "thread_changes"
CREATED_ISSUES_KEY: Final = "created_issues"
DELETED_ISSUES_KEY: Final = "deleted_issues"


class SnapshotIssueState(TypedDict):
    """One issue preimage inside an undo snapshot payload.

    ``id``, ``number``, and ``status`` are the identity every restore path reads
    unconditionally. The remaining fields are optional because compact deltas
    (issue #3226) record only the fields that actually changed, and legacy full
    snapshots never captured ``catalog_issue_id``.
    """

    id: int
    number: str
    status: str
    position: NotRequired[int]
    read_at: NotRequired[str | None]
    catalog_issue_id: NotRequired[int | None]
    last_rating: NotRequired[float | None]


class SnapshotThreadState(TypedDict, total=False):
    """One thread preimage inside an undo snapshot payload.

    Snapshot payloads are written by
    :func:`app.services.rate_service.snapshot_thread_states` and are JSON
    round-tripped through ``snapshots.thread_states``. Every field is optional
    because a payload is either a compact per-action delta (only changed
    fields) or a legacy full-library capture, and older payloads predate some
    fields. Restore code therefore reads fields through ``.get()`` with
    model-side fallbacks.
    """

    # Thread identity/state captured by full and compact thread captures.
    title: str
    format: str
    issues_remaining: int
    last_rating: float | None
    last_activity_at: str | None
    queue_position: int
    queue_position_is_manual: bool
    status: str
    notes: str | None
    is_test: bool
    created_at: str
    user_id: int
    is_blocked: bool
    # Issue-tracking projection carried by full captures.
    uses_issue_tracking: bool
    issue_states: list[SnapshotIssueState] | None
    total_issues: int | None
    next_unread_issue_id: int | None
    reading_progress: str | None
    # Compact per-action change lists (issue #3226).
    issue_changes: list[SnapshotIssueState]
    created_issues: list[SnapshotIssueState]
    deleted_issues: list[SnapshotIssueState]


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
