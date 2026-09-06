#!/usr/bin/env python3
"""Choose the native OmniRoute route that matches one factory assignment."""

from __future__ import annotations

import argparse

CODING_ROUTE = "auto/coding:free"
REVIEW_ROUTE = "auto/reasoning:free"


def route_for_assignment(mode: str, pr_stage: str = "") -> str:
    """Return the free OmniRoute intent route for the current factory work."""
    if mode == "pr" and pr_stage == "factory:review":
        return REVIEW_ROUTE
    return CODING_ROUTE


def main() -> int:
    """Print the route selected for a worker assignment."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("issue", "pr"))
    parser.add_argument("--pr-stage", default="")
    args = parser.parse_args()
    print(route_for_assignment(args.mode, args.pr_stage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
