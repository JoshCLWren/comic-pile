"""One-command Upstash cache usage report CLI.

Run from the repository root:

    uv run python -m scripts.cache_usage_report
    uv run python -m scripts.cache_usage_report --observed 12000 --provider-commands 14500
    uv run python -m scripts.cache_usage_report --json

The report reads the privacy-safe in-process observed command total from
:mod:`app.cache_metrics` unless ``--observed`` is supplied, and compares it to
the configured Upstash free-tier budget. Operator-supplied ``--provider-commands``
reflects the provider console month-to-date total.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.cache_usage import build_cache_usage_report, format_cache_usage_report


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
        provider_commands=args.provider_commands,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(format_cache_usage_report(report))

    return 0


if __name__ == "__main__":
    sys.exit(main())
