"""One-command cache usage, budget, and headroom report.

This module builds a single consolidated observability report for the cache
tier. It:

1. Queries the Upstash management REST API for current command usage
   (``total_monthly_requests``, ``daily_net_commands``, per-command breakdown,
   and hit/miss series when the database exposes them).
2. Compares that usage against the conservative monthly command budget defined
   in :mod:`app.cache_metrics` and reports the remaining headroom.
3. Surfaces the in-process cache command metrics (the privacy-safe hit/miss
   command families tracked by :data:`app.cache_metrics.cache_command_metrics`)
   in the same report so operators see both the provider's billed usage and
   the application's own command accounting.

The HTTP layer depends only on the standard library (``urllib``) and is fully
injectable, so the report can be built and tested without network access.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol

DEFAULT_UPSTASH_API_BASE = "https://api.upstash.com"
DEFAULT_TIMEOUT_SECONDS = 15.0

# The conservative plan budget and the upstream free-tier limit live in
# app.cache_metrics so the report and the cache runtime share one source of
# truth. Fall back to literals only when the application stack cannot be
# imported (for example on a thin monitoring box) so the tool still prints a
# meaningful budget figure.
try:
    from app.cache_metrics import (
        CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
        MONTHLY_HEADROOM_COMMANDS,
        UPSTASH_FREE_MONTHLY_COMMANDS,
        cache_command_metrics,
    )

    METRICS_AVAILABLE = True
except Exception:  # pragma: no cover - only when the app stack is unavailable
    CONSERVATIVE_MONTHLY_COMMAND_BUDGET = 350_000
    UPSTASH_FREE_MONTHLY_COMMANDS = 500_000
    MONTHLY_HEADROOM_COMMANDS = UPSTASH_FREE_MONTHLY_COMMANDS - CONSERVATIVE_MONTHLY_COMMAND_BUDGET
    cache_command_metrics = None
    METRICS_AVAILABLE = False


class UpstashApiError(RuntimeError):
    """Raised when the Upstash management API returns an error or is unreachable."""


class HttpGet(Protocol):
    """Injectable HTTP GET used for tests and the live management API."""

    def __call__(
        self, url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, bytes]:
        """Perform an HTTP GET and return ``(status_code, response_body)``."""
        ...


@dataclass
class UpstashUsage:
    """Parsed command-usage snapshot for one Upstash database."""

    database_id: str
    database_name: str | None
    total_monthly_requests: int
    daily_net_commands: int
    monthly_read_requests: int
    monthly_write_requests: int
    monthly_script_requests: int
    command_counts: dict[str, int] = field(default_factory=dict)
    hits_latest: int | None = None
    misses_latest: int | None = None
    total_monthly_bandwidth_bytes: int = 0
    db_request_limit: int | None = None


@dataclass
class CacheUsageReport:
    """Consolidated cache usage, budget, and headroom report."""

    generated_at: str
    upstash_configured: bool
    upstash: UpstashUsage | None
    budget_monthly: int
    free_tier_monthly: int
    conservative_headroom: int
    used_commands: int | None
    headroom_commands: int | None
    used_pct: float | None
    projected_month_end: int | None
    days_remaining: int | None
    in_process_metrics: dict[str, int]
    in_process_total: int
    notes: list[str] = field(default_factory=list)


class UpstashManagementClient:
    """Thin Basic-auth client for the Upstash developer API (v2)."""

    def __init__(
        self,
        email: str,
        api_key: str,
        api_base: str = DEFAULT_UPSTASH_API_BASE,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        http_get: HttpGet | None = None,
    ) -> None:
        """Create a management client.

        Args:
            email: Upstash account email (Basic-auth username).
            api_key: Upstash management API key (Basic-auth password).
            api_base: Management API base URL.
            timeout: Per-request timeout in seconds.
            http_get: Injectable HTTP GET for tests; defaults to ``urllib``.
        """
        self._email = email
        self._api_key = api_key
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        self._http_get = http_get

    def _get(self, path: str) -> dict:
        """GET one JSON management endpoint and return the decoded payload.

        Args:
            path: API path beginning with ``/`` (for example ``/v2/redis/databases``).

        Returns:
            Decoded JSON response body.

        Raises:
            UpstashApiError: On non-2xx status or unreachable endpoint.
        """
        url = f"{self._api_base}{path}"
        credentials = base64.b64encode(
            f"{self._email}:{self._api_key}".encode()
        ).decode("ascii")
        headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "User-Agent": "comic-pile-cache-usage-report/1",
        }
        if self._http_get is not None:
            status, body = self._http_get(url, headers, self._timeout)
        else:
            request = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    status, body = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                body = exc.read() if exc.fp else b""
            except urllib.error.URLError as exc:
                raise UpstashApiError(f"Upstash API unreachable: {exc.reason}") from exc
        if status >= 400:
            decoded = body.decode("utf-8", "replace")
            raise UpstashApiError(f"Upstash API {status}: {decoded[:500]}")
        return json.loads(body.decode("utf-8"))

    def list_databases(self) -> list[dict]:
        """Return all databases in the account."""
        result = self._get("/v2/redis/databases")
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "databases" in result:
            return result["databases"]
        return []

    def get_database_stats(self, database_id: str) -> dict:
        """Return the stats object for one database."""
        return self._get(f"/v2/redis/stats/{database_id}")

    def discover_database_id(self) -> str | None:
        """Pick a Redis database to report on, preferring a free-tier instance.

        Returns:
            The chosen ``database_id``, or ``None`` when the account has no
            Redis databases.
        """
        databases = self.list_databases()
        if not databases:
            return None
        free_first = [db for db in databases if db.get("type") == "free"]
        candidate = (free_first or databases)[0]
        return candidate.get("database_id")


def _safe_int(value: object) -> int:
    """Coerce an API value to ``int``, tolerating ``None``/strings."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _latest_value(series: object) -> int | None:
    """Return the most recent non-null ``y`` from an Upstash time-series field."""
    if not isinstance(series, list):
        return None
    for point in reversed(series):
        if isinstance(point, dict) and point.get("y") is not None:
            return _safe_int(point.get("y"))
    return None


def parse_usage(stats: dict, database: dict) -> UpstashUsage:
    """Build an :class:`UpstashUsage` from raw API payloads.

    Args:
        stats: Decoded ``/v2/redis/stats/{id}`` response.
        database: Decoded ``/v2/redis/databases`` entry for the same database.

    Returns:
        Parsed usage snapshot.
    """
    command_counts: dict[str, int] = {}
    raw_commands = stats.get("command_counts")
    if isinstance(raw_commands, list):
        for entry in raw_commands:
            if not isinstance(entry, dict):
                continue
            name = entry.get("metric_identifier")
            data_points = entry.get("data_points")
            if not isinstance(name, str) or not isinstance(data_points, list):
                continue
            command_counts[name] = sum(_safe_int(point.get("y")) for point in data_points)

    return UpstashUsage(
        database_id=str(database.get("database_id", stats.get("database_id", ""))),
        database_name=database.get("database_name"),
        total_monthly_requests=_safe_int(stats.get("total_monthly_requests")),
        daily_net_commands=_safe_int(stats.get("daily_net_commands")),
        monthly_read_requests=_safe_int(stats.get("total_monthly_read_requests")),
        monthly_write_requests=_safe_int(stats.get("total_monthly_write_requests")),
        monthly_script_requests=_safe_int(stats.get("total_monthly_script_requests")),
        command_counts=command_counts,
        hits_latest=_latest_value(stats.get("hits")),
        misses_latest=_latest_value(stats.get("misses")),
        total_monthly_bandwidth_bytes=_safe_int(stats.get("total_monthly_bandwidth")),
        db_request_limit=_safe_int(database.get("db_request_limit")) or None,
    )


def build_cache_usage_report(
    email: str | None = None,
    api_key: str | None = None,
    database_id: str | None = None,
    api_base: str = DEFAULT_UPSTASH_API_BASE,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    now: datetime | None = None,
    http_get: HttpGet | None = None,
) -> CacheUsageReport:
    """Build the consolidated cache usage report.

    Args:
        email: Upstash account email. When omitted, Upstash usage is skipped.
        api_key: Upstash management API key. When omitted, Upstash usage is skipped.
        database_id: Explicit database id; when omitted the account's first
            (preferably free-tier) Redis database is used.
        api_base: Management API base URL.
        timeout: Per-request timeout in seconds.
        now: Override clock (used by tests); defaults to UTC now.
        http_get: Injectable HTTP GET for tests; defaults to live ``urllib``.

    Returns:
        The consolidated :class:`CacheUsageReport`.
    """
    generated_at = (now or datetime.now(UTC)).isoformat()
    upstash_configured = bool(email and api_key)
    upstash: UpstashUsage | None = None
    notes: list[str] = []

    if upstash_configured:
        assert email is not None
        assert api_key is not None
        client = UpstashManagementClient(
            email=email,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            http_get=http_get,
        )
        try:
            resolved_id = database_id or client.discover_database_id()
            if resolved_id is None:
                notes.append("No Upstash Redis databases found for these credentials.")
                upstash_configured = False
            else:
                database = next(
                    (
                        db
                        for db in client.list_databases()
                        if db.get("database_id") == resolved_id
                    ),
                    {"database_id": resolved_id},
                )
                stats = client.get_database_stats(resolved_id)
                upstash = parse_usage(stats, database)
        except UpstashApiError as exc:
            notes.append(f"Upstash usage unavailable: {exc}")
            upstash_configured = False
    else:
        notes.append(
            "Upstash credentials not provided; set UPSTASH_EMAIL and UPSTASH_API_KEY "
            "to include live usage in the report."
        )

    used_commands = upstash.total_monthly_requests if upstash is not None else None
    budget_monthly = CONSERVATIVE_MONTHLY_COMMAND_BUDGET

    headroom_commands: int | None = None
    used_pct: float | None = None
    projected_month_end: int | None = None
    days_remaining: int | None = None

    if used_commands is not None:
        headroom_commands = budget_monthly - used_commands
        used_pct = round((used_commands / budget_monthly) * 100, 2) if budget_monthly else None
        current = (now or datetime.now(UTC)).date()
        days_in_month = _days_in_month(current)
        day_of_month = current.day
        days_remaining = days_in_month - day_of_month
        if day_of_month > 0:
            daily_average = used_commands / day_of_month
            projected_month_end = int(daily_average * days_in_month)

    in_process_metrics = (
        dict(cache_command_metrics.snapshot()) if cache_command_metrics is not None else {}
    )
    in_process_total = (
        cache_command_metrics.total() if cache_command_metrics is not None else 0
    )

    if not METRICS_AVAILABLE:
        notes.append(
            "app.cache_metrics unavailable; using fallback budget constants "
            f"({budget_monthly:,} commands)."
        )

    return CacheUsageReport(
        generated_at=generated_at,
        upstash_configured=upstash_configured,
        upstash=upstash,
        budget_monthly=budget_monthly,
        free_tier_monthly=UPSTASH_FREE_MONTHLY_COMMANDS,
        conservative_headroom=MONTHLY_HEADROOM_COMMANDS,
        used_commands=used_commands,
        headroom_commands=headroom_commands,
        used_pct=used_pct,
        projected_month_end=projected_month_end,
        days_remaining=days_remaining,
        in_process_metrics=in_process_metrics,
        in_process_total=in_process_total,
        notes=notes,
    )


def _days_in_month(current: date) -> int:
    """Return the number of days in ``current``'s month."""
    if current.month == 12:
        next_month = current.replace(year=current.year + 1, month=1, day=1)
    else:
        next_month = current.replace(month=current.month + 1, day=1)
    return (next_month - current.replace(day=1)).days


def render_cache_usage_report(report: CacheUsageReport) -> str:
    """Render the report as human-readable text.

    Args:
        report: The consolidated report to render.

    Returns:
        Multi-line text suitable for terminal output.
    """
    lines: list[str] = []
    lines.append("Cache usage report")
    lines.append(f"Generated: {report.generated_at}")
    lines.append("")

    lines.append("Upstash usage")
    if report.upstash is None:
        lines.append("  (skipped) live usage not available")
    else:
        usage = report.upstash
        lines.append(f"  database: {usage.database_name or usage.database_id}")
        lines.append(f"  this month (commands): {usage.total_monthly_requests:,}")
        lines.append(f"  today (commands):      {usage.daily_net_commands:,}")
        lines.append(
            f"  read / write / script: {usage.monthly_read_requests:,} / "
            f"{usage.monthly_write_requests:,} / {usage.monthly_script_requests:,}"
        )
        if usage.hits_latest is not None or usage.misses_latest is not None:
            lines.append(f"  hits / misses:         {usage.hits_latest} / {usage.misses_latest}")
        if usage.command_counts:
            lines.append("  command breakdown:")
            for name in sorted(usage.command_counts):
                lines.append(f"    {name}: {usage.command_counts[name]:,}")

    lines.append("")
    lines.append("Budget")
    lines.append(f"  conservative monthly budget: {report.budget_monthly:,} commands")
    lines.append(f"  upstream free-tier limit:   {report.free_tier_monthly:,} commands")

    lines.append("")
    lines.append("Headroom")
    if report.used_commands is None:
        lines.append("  (skipped) no live usage to compare against budget")
    else:
        lines.append(
            f"  used this month: {report.used_commands:,} ({report.used_pct}% of budget)"
        )
        lines.append(f"  remaining headroom: {report.headroom_commands:,} commands")
        if report.projected_month_end is not None:
            lines.append(f"  projected month-end: {report.projected_month_end:,} commands")
        if report.days_remaining is not None:
            lines.append(f"  days remaining in month: {report.days_remaining}")

    lines.append("")
    lines.append("In-process cache metrics (app.cache_metrics)")
    lines.append(f"  total commands recorded: {report.in_process_total:,}")
    if report.in_process_metrics:
        for name in sorted(report.in_process_metrics):
            lines.append(f"    {name}: {report.in_process_metrics[name]:,}")
    else:
        lines.append("  (no in-process commands recorded in this process)")

    if report.notes:
        lines.append("")
        lines.append("Notes")
        for note in report.notes:
            lines.append(f"  - {note}")

    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser.

    Returns:
        Configured ``argparse.ArgumentParser`` for the report CLI.
    """
    parser = argparse.ArgumentParser(
        description="Print Upstash cache usage, budget, and headroom in one command.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--email", default=os.environ.get("UPSTASH_EMAIL"))
    parser.add_argument("--api-key", default=os.environ.get("UPSTASH_API_KEY"))
    parser.add_argument("--database-id", default=os.environ.get("UPSTASH_DATABASE_ID"))
    parser.add_argument("--api-base", default=DEFAULT_UPSTASH_API_BASE)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the raw report as JSON instead of human-readable text.",
    )
    return parser


def _report_to_dict(report: CacheUsageReport) -> dict:
    """Serialize a report to a JSON-ready mapping."""
    return {
        "generated_at": report.generated_at,
        "upstash_configured": report.upstash_configured,
        "upstash": (
            {
                "database_id": report.upstash.database_id,
                "database_name": report.upstash.database_name,
                "total_monthly_requests": report.upstash.total_monthly_requests,
                "daily_net_commands": report.upstash.daily_net_commands,
                "monthly_read_requests": report.upstash.monthly_read_requests,
                "monthly_write_requests": report.upstash.monthly_write_requests,
                "monthly_script_requests": report.upstash.monthly_script_requests,
                "command_counts": report.upstash.command_counts,
                "hits_latest": report.upstash.hits_latest,
                "misses_latest": report.upstash.misses_latest,
                "total_monthly_bandwidth_bytes": report.upstash.total_monthly_bandwidth_bytes,
                "db_request_limit": report.upstash.db_request_limit,
            }
            if report.upstash is not None
            else None
        ),
        "budget_monthly": report.budget_monthly,
        "free_tier_monthly": report.free_tier_monthly,
        "conservative_headroom": report.conservative_headroom,
        "used_commands": report.used_commands,
        "headroom_commands": report.headroom_commands,
        "used_pct": report.used_pct,
        "projected_month_end": report.projected_month_end,
        "days_remaining": report.days_remaining,
        "in_process_metrics": report.in_process_metrics,
        "in_process_total": report.in_process_total,
        "notes": report.notes,
    }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the cache usage report.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv``).

    Returns:
        Process exit code (``0`` on success).
    """
    args = _build_arg_parser().parse_args(argv)
    report = build_cache_usage_report(
        email=args.email,
        api_key=args.api_key,
        database_id=args.database_id,
        api_base=args.api_base,
        timeout=args.timeout,
    )
    if args.json:
        print(json.dumps(_report_to_dict(report), indent=2))
    else:
        print(render_cache_usage_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
