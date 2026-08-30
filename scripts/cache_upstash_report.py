#!/usr/bin/env python3
"""Command-line entry point for the Upstash cache usage report.

Thin wrapper that exposes :mod:`app.cache_usage_report` as a runnable script so
``python -m scripts.cache_upstash_report`` prints the one-command usage, budget,
and headroom report by querying the Upstash REST API. All business logic lives
in :mod:`app.cache_usage_report`.
"""

from __future__ import annotations

import sys

from app.cache_usage_report import main


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
