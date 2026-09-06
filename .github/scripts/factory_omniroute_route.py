#!/usr/bin/env python3
"""Choose the native OmniRoute route that matches one factory assignment.

TEMPORARY 2026-09-06: ``auto/coding:free`` is skipped or hanging
(``ALL_TARGETS_SKIPPED``). After the assignment-aware native intent fails that
way, Entry may fall back once to ``auto/best-free``. Disable with
``FACTORY_OMNIROUTE_CAPACITY_BRIDGE=off``. Remove the bridge when
``auto/coding:free`` is healthy. This is not backing-model catalog selection.
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

CODING_ROUTE = "auto/coding:free"
REVIEW_ROUTE = "auto/reasoning:free"

# TEMPORARY 2026-09-06. Delete this constant and the env default to revert.
CAPACITY_BRIDGE_ROUTE = "auto/best-free"
CAPACITY_BRIDGE_ENV = "FACTORY_OMNIROUTE_CAPACITY_BRIDGE"

NATIVE_INTENT_ROUTES = frozenset({CODING_ROUTE, REVIEW_ROUTE})
CAPACITY_SKIP_RE = re.compile(
    r"all targets were skipped|pre-dispatch filters|ALL_TARGETS_SKIPPED|"
    r"temporar(?:il)?y unavailable|service unavailable",
    re.IGNORECASE,
)


def route_for_assignment(mode: str, pr_stage: str = "") -> str:
    """Return the free OmniRoute intent route for the current factory work."""
    if mode == "pr" and pr_stage == "factory:review":
        return REVIEW_ROUTE
    return CODING_ROUTE


def capacity_bridge_enabled() -> bool:
    """Return whether the temporary auto/best-free smoke bridge is on."""
    raw = os.environ.get(CAPACITY_BRIDGE_ENV, CAPACITY_BRIDGE_ROUTE)
    return raw.strip().lower() not in {"", "0", "off", "false", "no"}


def capacity_bridge_route() -> str:
    """Return the temporary capacity-bridge route, or empty when disabled."""
    if not capacity_bridge_enabled():
        return ""
    raw = os.environ.get(CAPACITY_BRIDGE_ENV, CAPACITY_BRIDGE_ROUTE).strip()
    if raw.lower() in {"1", "on", "true", "yes", CAPACITY_BRIDGE_ROUTE}:
        return CAPACITY_BRIDGE_ROUTE
    return raw


def is_native_intent_route(route: str) -> bool:
    """Return whether a route is a durable native OmniRoute intent."""
    return route in NATIVE_INTENT_ROUTES


def is_capacity_skip_failure(text: str, status: int = 1) -> bool:
    """Return whether smoke failed because OmniRoute skipped or timed out."""
    if status in {124, 137, 143}:
        return True
    return bool(CAPACITY_SKIP_RE.search(text or ""))


def next_route_after_smoke_failure(primary: str, status: int, log_text: str) -> str:
    """Return the one-shot capacity-bridge route after a native-intent skip.

    Review assignments still smoke ``auto/reasoning:free`` first. The bridge is
    used only after that native intent (or coding) is skipped or times out.
    """
    if primary not in NATIVE_INTENT_ROUTES:
        return ""
    if not is_capacity_skip_failure(log_text, status):
        return ""
    bridge = capacity_bridge_route()
    if not bridge or bridge == primary:
        return ""
    return bridge


def main() -> int:
    """Print the route selected for a worker assignment or smoke fallback."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("issue", "pr"))
    parser.add_argument("--pr-stage", default="")
    parser.add_argument("--capacity-bridge", action="store_true")
    parser.add_argument("--next-after-smoke-failure", action="store_true")
    parser.add_argument("--primary", default="")
    parser.add_argument("--status", type=int, default=1)
    parser.add_argument("--log-file", default="")
    args = parser.parse_args()
    if args.capacity_bridge:
        print(capacity_bridge_route())
        return 0
    if args.next_after_smoke_failure:
        log_text = Path(args.log_file).read_text(encoding="utf-8") if args.log_file else ""
        print(next_route_after_smoke_failure(args.primary, args.status, log_text))
        return 0
    if not args.mode:
        parser.error("--mode is required unless querying the capacity bridge")
    print(route_for_assignment(args.mode, args.pr_stage))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
