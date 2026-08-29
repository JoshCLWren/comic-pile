"""One-command Upstash cache usage report versus the monthly budget.

The report is the operator-facing observability surface for the cache
re-enable evaluation. It compares the application's privacy-safe observed
command count (from :mod:`app.cache_metrics`) to the configured Upstash
free-tier budget and, when supplied, the provider-reported command count.

The provider command count is operator-supplied (for example, from the Upstash
console or a metrics export) because Upstash does not expose a stable
month-to-date command total through the Redis protocol; the application never
stores credentials or calls the provider REST API directly here. Keeping it
injected keeps the report deterministic and testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.cache_metrics import (
    CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
    MONTHLY_HEADROOM_COMMANDS,
    UPSTASH_FREE_MONTHLY_COMMANDS,
    cache_command_metrics,
)

DEFAULT_ALERT_FRACTION = 0.8


@dataclass(slots=True)
class CacheUsageReport:
    """Structured cache usage vs budget report."""

    observed_commands: int
    provider_commands: int | None
    application_budget: int
    free_allowance: int
    observed_ratio: float
    provider_ratio: float | None
    headroom_remaining: int
    alert_fraction: float
    status: str
    recommendation: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable view of the report."""
        return asdict(self)


def build_cache_usage_report(
    observed_commands: int | None = None,
    provider_commands: int | None = None,
    budget: int = CONSERVATIVE_MONTHLY_COMMAND_BUDGET,
    free_allowance: int = UPSTASH_FREE_MONTHLY_COMMANDS,
    alert_fraction: float = DEFAULT_ALERT_FRACTION,
) -> CacheUsageReport:
    """Build a cache usage report against the monthly budget.

    Args:
        observed_commands: Application-observed command count; defaults to the
            live :data:`app.cache_metrics.cache_command_metrics` total.
        provider_commands: Optional provider-reported month-to-date command
            count from the Upstash console or a metrics export.
        budget: Operating application command budget.
        free_allowance: Upstash documented free-tier monthly allowance.
        alert_fraction: Fraction of ``budget`` that marks the near-limit band.

    Returns:
        A populated :class:`CacheUsageReport`.
    """
    observed = observed_commands if observed_commands is not None else cache_command_metrics.total()
    if observed < 0:
        raise ValueError("observed cache command usage cannot be negative")

    observed_ratio = observed / budget if budget > 0 else float("inf")
    provider_ratio: float | None = None
    if provider_commands is not None:
        if provider_commands < 0:
            raise ValueError("provider cache command usage cannot be negative")
        provider_ratio = provider_commands / free_allowance if free_allowance > 0 else float("inf")

    headroom_remaining = max(budget - observed, 0)

    if observed_ratio >= 1.0:
        status = "over-budget"
        recommendation = (
            "Observed usage reached the monthly application budget. Disable "
            "CACHE_ENABLED and investigate command growth before raising the budget."
        )
    elif observed_ratio >= alert_fraction:
        status = "near-limit"
        recommendation = (
            "Approaching the monthly application budget. Keep the quota guardrail "
            "throttling enabled and watch the Upstash console for headroom burn."
        )
    else:
        status = "ok"
        recommendation = (
            "Within budget. Keep CACHE_ENABLED gated behind production traffic "
            "evidence per the re-enable decision."
        )

    return CacheUsageReport(
        observed_commands=observed,
        provider_commands=provider_commands,
        application_budget=budget,
        free_allowance=free_allowance,
        observed_ratio=observed_ratio,
        provider_ratio=provider_ratio,
        headroom_remaining=headroom_remaining,
        alert_fraction=alert_fraction,
        status=status,
        recommendation=recommendation,
    )


def format_cache_usage_report(report: CacheUsageReport) -> str:
    """Render a human-readable multi-line report for the CLI."""
    lines = [
        "ComicPile cache usage vs Upstash budget",
        "=" * 40,
        f"Status              : {report.status}",
        f"Observed commands   : {report.observed_commands}",
        f"Application budget  : {report.application_budget}",
        f"Observed usage      : {report.observed_ratio:.1%}",
        f"Headroom remaining  : {report.headroom_remaining}",
        f"Reserved headroom   : {MONTHLY_HEADROOM_COMMANDS} ({MONTHLY_HEADROOM_COMMANDS / UPSTASH_FREE_MONTHLY_COMMANDS:.0%} of free tier)",
    ]
    if report.provider_commands is not None:
        provider_ratio = report.provider_ratio if report.provider_ratio is not None else 0.0
        lines.append(
            f"Provider commands    : {report.provider_commands} ({provider_ratio:.1%} of free tier)"
        )
    lines.append("")
    lines.append(f"Recommendation: {report.recommendation}")
    return "\n".join(lines)
