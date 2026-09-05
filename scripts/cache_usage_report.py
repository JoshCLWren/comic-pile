"""One-command Upstash cache usage report CLI.

Run from the repository root:

    uv run python -m scripts.cache_usage_report
    uv run python -m scripts.cache_usage_report --observed 12000 --provider-commands 14500
    uv run python -m scripts.cache_usage_report --json

The report reads the privacy-safe in-process observed command total from
:mod:`app.cache_metrics` unless ``--observed`` is supplied, and compares it to
the configured Upstash free-tier budget. ``--provider-commands`` is the
operator-supplied Upstash console month-to-date total. When that flag is
omitted and ``UPSTASH_EMAIL`` plus ``UPSTASH_API_KEY`` are set, the CLI
fills provider commands from the Upstash management API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.cache_usage import build_cache_usage_report, format_cache_usage_report


def resolve_provider_commands(explicit: int | None) -> int | None:
    """Return provider month-to-date commands from CLI, then Upstash, then none.

    Args:
        explicit: Operator-supplied ``--provider-commands`` value.

    Returns:
        A non-negative command count, or ``None`` when no provider figure is
        available. Management credentials are read from ``UPSTASH_EMAIL`` and
        ``UPSTASH_API_KEY`` only when the explicit count is omitted.
    """
    if explicit is not None:
        return explicit
    email = os.environ.get("UPSTASH_EMAIL")
    api_key = os.environ.get("UPSTASH_API_KEY")
    if not email or not api_key:
        return None
    from app.cache_usage_report import build_cache_usage_report as build_upstash_report

    live = build_upstash_report(email=email, api_key=api_key)
    return live.used_commands


def main(argv: list[str] | None = None) -> int:
    """Print the cache usage report and return a process exit code."""
    parser = argparse.ArgumentParser(description="Report cache usage vs Upstash budget")
    parser.add_argument(
        "--observed",
        type=int,
        default=None,
        help="Application-observed monthly command count (defaults to live metrics)",
    )
    parser.add_argument(
        "--provider-commands",
        type=int,
        default=None,
        help="Provider-reported month-to-date command count (from Upstash console)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args(argv)

    report = build_cache_usage_report(
        observed_commands=args.observed,
        provider_commands=resolve_provider_commands(args.provider_commands),
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(format_cache_usage_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
