"""Generic domain types for the work lattice."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC


WorkerId = str
"""Opaque identifier for a worker slot."""


@dataclass(frozen=True, order=False)
class Lease:
    """A durable, time-bound claim on a work node by a worker."""

    worker: WorkerId
    acquired_at: datetime
    ttl_seconds: int = 3600
    active_run_epoch: int | None = None
    latest_activity_epoch: int | None = None

    def is_expired(self, now: datetime) -> bool:
        """Check whether the lease has expired at the given time."""
        from latticery.lease import lease_is_expired

        return lease_is_expired(
            worker=self.worker,
            latest_activity_epoch=self.latest_activity_epoch,
            now_epoch=int(now.timestamp()),
            ttl_seconds=self.ttl_seconds,
            active_run_epoch=self.active_run_epoch,
        )


@dataclass(frozen=True)
class Stage:
    """Lifecycle stage of a work node, expressed without representation syntax."""

    name: str

    def __post_init__(self) -> None:
        """Validate stage name on initialization."""
        if not self.name:
            raise ValueError("Stage name must be non-empty")


@dataclass(frozen=True, order=False)
class Candidate:
    """A ranked executable unit of work."""

    kind: str  # e.g., 'issue', 'pr'
    number: int
    lane: int
    priority: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    linked_issue: int | None = None
    stage: Stage | None = None
    producer_worker: WorkerId | None = None
    conflicted: bool = False

    def sort_key(self) -> tuple[int, int, float, int]:
        """Return deterministic sort tuple for ordering."""
        return (self.lane, -self.priority, self.created_at.timestamp(), self.number)


@dataclass(frozen=True)
class WorkNode:
    """A generic representable work item (issue or PR abstraction)."""

    number: int
    kind: str
    labels: frozenset[str] = field(default_factory=frozenset)
    body: str = ""
    state: str = "OPEN"
    branch: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
