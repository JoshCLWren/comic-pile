#!/usr/bin/env python3
"""Regression coverage for factory eligibility of epic and PRD issues."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from factory_work_policy import build_candidates  # noqa: E402


def issue(number: int, title: str, *extra_labels: str) -> dict[str, object]:
    """Return a minimal unowned factory issue fixture."""
    return {
        "number": number,
        "state": "OPEN",
        "title": title,
        "labels": [
            {"name": "factory"},
            {"name": "factory:unowned"},
            *({"name": label} for label in extra_labels),
        ],
        "createdAt": "2026-08-21T00:00:00Z",
    }


def test_unblocked_epic_and_prd_are_factory_candidates() -> None:
    """Epic and PRD titles should no longer be excluded solely by title."""
    candidates = build_candidates(
        [
            issue(2001, "Epic: Deliver the next factory phase"),
            issue(2002, "PRD: Define the next product capability"),
        ],
        [],
    )

    assert {candidate.number for candidate in candidates} == {2001, 2002}


def test_blocked_epic_and_prd_remain_ineligible() -> None:
    """Removing title filtering must not bypass explicit blockers."""
    candidates = build_candidates(
        [
            issue(2003, "Epic: Blocked work", "ralph-status:blocked"),
            issue(2004, "PRD: Human-gated work", "factory:blocked"),
        ],
        [],
    )

    assert candidates == []
