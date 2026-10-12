"""Shared durable store for performance-alarm counters and incidents.

Process memory cannot implement the #3552 daily threshold on Vercel
serverless: each instance would keep its own count. Production uses
Postgres via :class:`PostgresPerfAlarmStore`. Tests use
:class:`InMemoryPerfAlarmStore`, which two evaluators can share.
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import perf_alarm_repository as repo


class PerfAlarmStore(Protocol):
    """Durable fingerprint state shared across alarm evaluators."""

    async def increment_daily_hit(self, fingerprint: str, utc_day: date) -> int:
        """Increment and return the warm over-budget hit count for ``utc_day``."""
        ...

    async def get_open_issue(self, fingerprint: str) -> int | None:
        """Return the stored open GitHub issue number, if any."""
        ...

    async def get_closed_issue(self, fingerprint: str) -> int | None:
        """Return the stored last-closed GitHub issue number, if any."""
        ...

    async def mark_open(self, fingerprint: str, issue_number: int) -> None:
        """Record that ``fingerprint`` has open GitHub issue ``issue_number``."""
        ...

    async def mark_closed(self, fingerprint: str, issue_number: int) -> None:
        """Record a close and reset daily hits so regressions need N again."""
        ...

    async def try_claim_filing(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may create a new GitHub issue."""
        ...

    async def clear_filing_claim(self, fingerprint: str) -> None:
        """Release a filing claim after a failed GitHub create."""
        ...

    async def try_claim_comment(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may post a GitHub comment."""
        ...

    async def commit(self) -> None:
        """Persist pending mutations. No-op for the in-memory store."""
        ...


class InMemoryPerfAlarmStore:
    """Process-local store that multiple evaluators can share in tests."""

    def __init__(self) -> None:
        """Initialize empty shared state."""
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, date], int] = {}
        self._open: dict[str, int] = {}
        self._closed: dict[str, int] = {}
        self._last_comment: dict[str, datetime] = {}
        self._filing_claimed: dict[str, datetime] = {}

    async def increment_daily_hit(self, fingerprint: str, utc_day: date) -> int:
        """Increment and return the warm over-budget hit count for ``utc_day``."""
        with self._lock:
            key = (fingerprint, utc_day)
            self._hits[key] = self._hits.get(key, 0) + 1
            return self._hits[key]

    async def get_open_issue(self, fingerprint: str) -> int | None:
        """Return the stored open GitHub issue number, if any."""
        with self._lock:
            return self._open.get(fingerprint)

    async def get_closed_issue(self, fingerprint: str) -> int | None:
        """Return the stored last-closed GitHub issue number, if any."""
        with self._lock:
            return self._closed.get(fingerprint)

    async def mark_open(self, fingerprint: str, issue_number: int) -> None:
        """Record that ``fingerprint`` has open GitHub issue ``issue_number``."""
        with self._lock:
            self._open[fingerprint] = issue_number
            self._closed.pop(fingerprint, None)
            self._filing_claimed.pop(fingerprint, None)

    async def mark_closed(self, fingerprint: str, issue_number: int) -> None:
        """Record a close and reset daily hits so regressions need N again."""
        with self._lock:
            self._closed[fingerprint] = issue_number
            self._open.pop(fingerprint, None)
            self._filing_claimed.pop(fingerprint, None)
            for key in [k for k in self._hits if k[0] == fingerprint]:
                del self._hits[key]

    async def try_claim_filing(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may create a new GitHub issue."""
        current = now if now is not None else datetime.now(UTC)
        stale = current - timedelta(minutes=5)
        with self._lock:
            if fingerprint in self._open:
                return False
            claimed = self._filing_claimed.get(fingerprint)
            if claimed is not None and claimed >= stale:
                return False
            self._filing_claimed[fingerprint] = current
            return True

    async def clear_filing_claim(self, fingerprint: str) -> None:
        """Release a filing claim after a failed GitHub create."""
        with self._lock:
            self._filing_claimed.pop(fingerprint, None)

    async def try_claim_comment(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may post a GitHub comment."""
        current = now if now is not None else datetime.now(UTC)
        stale = current - timedelta(hours=1)
        with self._lock:
            last = self._last_comment.get(fingerprint)
            if last is not None and last > stale:
                return False
            self._last_comment[fingerprint] = current
            return True

    async def commit(self) -> None:
        """No-op: in-memory mutations are already visible to other evaluators."""
        return


class PostgresPerfAlarmStore:
    """Postgres-backed store using the perf-alarm repository."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind this store to one async session.

        Args:
            db: Database session. The caller commits.
        """
        self._db = db

    async def increment_daily_hit(self, fingerprint: str, utc_day: date) -> int:
        """Increment and return the warm over-budget hit count for ``utc_day``."""
        return await repo.increment_daily_hit(
            self._db, fingerprint=fingerprint, utc_day=utc_day
        )

    async def get_open_issue(self, fingerprint: str) -> int | None:
        """Return the stored open GitHub issue number, if any."""
        return await repo.get_open_issue(self._db, fingerprint=fingerprint)

    async def get_closed_issue(self, fingerprint: str) -> int | None:
        """Return the stored last-closed GitHub issue number, if any."""
        return await repo.get_closed_issue(self._db, fingerprint=fingerprint)

    async def mark_open(self, fingerprint: str, issue_number: int) -> None:
        """Record that ``fingerprint`` has open GitHub issue ``issue_number``."""
        await repo.mark_open(
            self._db, fingerprint=fingerprint, issue_number=issue_number
        )

    async def mark_closed(self, fingerprint: str, issue_number: int) -> None:
        """Record a close and reset daily hits so regressions need N again."""
        await repo.mark_closed(
            self._db, fingerprint=fingerprint, issue_number=issue_number
        )

    async def try_claim_filing(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may create a new GitHub issue."""
        return await repo.try_claim_filing(
            self._db, fingerprint=fingerprint, now=now
        )

    async def clear_filing_claim(self, fingerprint: str) -> None:
        """Release a filing claim after a failed GitHub create."""
        await repo.clear_filing_claim(self._db, fingerprint=fingerprint)

    async def try_claim_comment(
        self,
        fingerprint: str,
        now: datetime | None = None,
    ) -> bool:
        """Return True when this caller may post a GitHub comment."""
        return await repo.try_claim_comment(
            self._db, fingerprint=fingerprint, now=now
        )

    async def commit(self) -> None:
        """Commit the bound session so other instances see the mutation."""
        await self._db.commit()
