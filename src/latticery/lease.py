"""Pure lease-expiry logic without representation syntax."""

from __future__ import annotations


def lease_is_expired(
    worker: str,
    *,
    latest_activity_epoch: int | None,
    now_epoch: int,
    ttl_seconds: int = 3600,
    active_run_epoch: int | None = None,
) -> bool:
    """Return whether a lease can be proven stale.

    Args:
        worker: opaque worker identifier.
        latest_activity_epoch: epoch of latest activity for fixed workers.
        now_epoch: current epoch.
        ttl_seconds: time-to-live in seconds.
        active_run_epoch: epoch of an unresolved active run, if any.
    """
    # If there is an unresolved active run for a fixed worker, the lease
    # is not stale regardless of time since activity.
    if active_run_epoch is not None:
        # Presence of unresolved runs preserves lease unless explicitly
        # released; this models the conservative fail-closed behavior.
        return False

    if latest_activity_epoch is None:
        # No activity recorded; treat as stale only for non-fixed workers when
        # needed, but conservative policy keeps it alive until explicitly broken.
        return False

    return now_epoch - latest_activity_epoch > ttl_seconds
