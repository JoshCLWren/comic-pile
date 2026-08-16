#!/usr/bin/env python3
"""Deterministic assignment and lease reconciliation for ComicPile factories.

The control plane owns repository-wide prioritization. Fixed-model workers only
execute the target currently leased to their ``factory:<n>`` owner label.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

REPO = os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile")
NON_EXECUTABLE_ISSUES = {679, 1093, 1109}

OWNER_RE = re.compile(r"^factory:(?:unowned|local|[1-9]|[1-3][0-9]|4[0-6])$")
# Factories 1-5 are scheduled ChatGPT workers. The fixed-model entry workflow
# only owns 6-46, so this controller must respect 1-5 leases but never infer
# their liveness from fixed-model Actions runs.
FIXED_OWNER_RE = re.compile(r"^factory:(?P<worker>[6-9]|[1-3][0-9]|4[0-6])$")
STAGE_LABELS = {
    "factory:building",
    "factory:review",
    "factory:changes-requested",
    "factory:ci",
    "factory:ready",
    "factory:blocked",
}
INFRA_LABELS = {
    "infrastructure",
    "e2e-infrastructure",
    "policy-change",
    "docs",
    "documentation",
    "quality-control",
}
BLOCKED_LABELS = {
    "factory:blocked",
    "ralph-status:blocked",
    "wontfix",
    "invalid",
    "duplicate",
}
LEASE_ACTIVITY_PATTERNS = (
    re.compile(r"comic-pile-factory-implement-(?:claim|progress)-v3:issue-\d+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-fix-(?:claim|progress)-v3:[^:>]+:[^:>]+:(\d{10})"),
    re.compile(r"comic-pile-factory-review-claim-v2:[^:>]+:[^:>]+:(\d{10})"),
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def env_positive_int(name: str, default: int) -> int:
    """Return a positive integer environment setting or its safe default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"[factory-controller] ignoring non-numeric {name}={raw!r}; using {default}",
            file=sys.stderr,
        )
        return default
    if value <= 0:
        print(
            f"[factory-controller] ignoring non-positive {name}={raw!r}; using {default}",
            file=sys.stderr,
        )
        return default
    return value


LOCAL_LEASE_TTL_SECONDS = env_positive_int("FACTORY_LOCAL_LEASE_TTL_SECONDS", 3600)
GH_TIMEOUT_SECONDS = env_positive_int("FACTORY_GH_TIMEOUT_SECONDS", 120)


@dataclass(frozen=True)
class Candidate:
    kind: str
    number: int
    lane: int
    priority: int
    created_at: str
    linked_issue: int | None = None

    def sort_key(self) -> tuple[int, int, float, int]:
        # This preserves the fleet's established newest-first tie break. The
        # canonical policy explicitly requires it for equal-priority user bugs.
        return (self.lane, -self.priority, -parse_time(self.created_at), -self.number)


def parse_time(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def labels_of(item: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for label in item.get("labels") or []:
        name = label.get("name") if isinstance(label, dict) else label
        if name:
            result.add(str(name))
    return result


def owner_of(labels: Iterable[str]) -> str | None:
    owners = [label for label in labels if OWNER_RE.fullmatch(label)]
    active = [label for label in owners if label != "factory:unowned"]
    if active:
        # Multiple active owners are an inconsistent state, but they are still
        # occupied. Returning one prevents accidental theft until reconciliation.
        return sorted(active)[0]
    return "factory:unowned" if "factory:unowned" in owners else None


def priority_rank(labels: Iterable[str]) -> int:
    labels = set(labels)
    if "ralph-priority:critical" in labels or "priority:P0" in labels:
        return 4
    if "ralph-priority:high" in labels or "priority: high" in labels:
        return 3
    if "ralph-priority:medium" in labels:
        return 2
    if "ralph-priority:low" in labels:
        return 1
    return 0


def linked_issue_from_branch(branch: str | None) -> int | None:
    if not branch:
        return None
    # Canonical fixed-model branches are factory/<worker>-<issue>-<suffix>.
    # Do not guess that factory/<n>-<suffix> encodes an issue because the
    # worker-side parser does not support that ambiguous shape either.
    match = re.match(r"^factory/\d+-(\d+)-", branch)
    return int(match.group(1)) if match else None


def provenance_lane(labels: set[str]) -> int:
    # Provenance beats generic bug classification. E2E-discovered bugs stay in
    # their explicit fallback lane even if another generic label is present.
    if "e2e-discovered" in labels:
        return 4
    if labels & INFRA_LABELS:
        return 5
    if "user-reported" in labels and "bug" in labels:
        return 1
    return 3


def item_is_unowned(labels: set[str]) -> bool:
    return owner_of(labels) in (None, "factory:unowned")


def issue_is_static_candidate(issue: dict[str, Any], suppressing_pr_issues: set[int]) -> bool:
    number = int(issue["number"])
    labels = labels_of(issue)
    title = str(issue.get("title") or "")
    if number in NON_EXECUTABLE_ISSUES or number in suppressing_pr_issues:
        return False
    if title.startswith(("Epic:", "PRD:")):
        return False
    if labels & BLOCKED_LABELS:
        return False
    if "ralph-status:done" in labels or "factory:ready" in labels:
        return False
    return item_is_unowned(labels)


def pr_is_static_candidate(pr: dict[str, Any], issue_map: dict[int, dict[str, Any]]) -> bool:
    if pr.get("isDraft"):
        return False
    labels = labels_of(pr)
    head = str(pr.get("headRefName") or "")
    if "factory" not in labels and not head.startswith("factory/"):
        return False
    if labels & BLOCKED_LABELS or "factory:ready" in labels:
        return False
    if not item_is_unowned(labels):
        return False
    linked = linked_issue_from_branch(head)
    if linked is not None and linked in issue_map:
        issue_labels = labels_of(issue_map[linked])
        if not item_is_unowned(issue_labels) or issue_labels & BLOCKED_LABELS:
            return False
    return True


def pr_suppresses_issue_candidate(pr: dict[str, Any], issue_map: dict[int, dict[str, Any]]) -> bool:
    """Return whether this PR should stand in for its linked issue in the queue.

    Ready PRs are owned by the merge controller. Other PRs suppress duplicate
    issue implementation only when the PR itself is executable. Draft, blocked,
    or otherwise ineligible PRs must never make the linked issue disappear.
    """
    labels = labels_of(pr)
    if "factory:ready" in labels and not pr.get("isDraft"):
        return True
    return pr_is_static_candidate(pr, issue_map)


def build_candidates(
    issues: list[dict[str, Any]], prs: list[dict[str, Any]]
) -> list[Candidate]:
    issue_map = {int(issue["number"]): issue for issue in issues}
    suppressing_pr_issues = {
        linked
        for pr in prs
        if (linked := linked_issue_from_branch(pr.get("headRefName"))) is not None
        and pr_suppresses_issue_candidate(pr, issue_map)
    }
    candidates: list[Candidate] = []

    for is²È="25Ý¹•È°ÍÑ…”¤(€€€€€€€€€€€¥˜¹½ÐÑ…É•Ñ}½Ý¹•‘}‰ä¡¹Õµ‰•È°½Ý¹•È¤è(€€€€€€€€€€€€€€€É•±•…Í•}Ù•É¥™¥•‘}±…¥µÌ¡±…¥µ•¤(€€€€€€€€€€€€€€€É•ÑÕÉ¸…±Í”(€€€€€€€€€€€±…¥µ•¹…ÁÁ•¹¡¹Õµ‰•È¤(€€€•á•ÁÐá•ÁÑ¥½¸è(€€€€€€€É•±•…Í•}Ù•É¥™¥•‘}±…¥µÌ¡±…¥µ•¤(€€€€€€€É…¥Í”(€€€É•ÑÕÉ¸QÉÕ”(()‘•˜™±…ÑÑ•¹}Á…•Ì¡Á…•Ìè¹ä¤€´ø±¥ÍÑm‘¥ÑmÍÑÈ°¹åutè(€€€É•ÍÕ±Ðè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€™½ÈÁ…”¥¸Á…•Ì½Èmtè(€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Á…”°±¥ÍÐ¤è(€€€€€€€€€€€É•ÍÕ±Ð¹•áÑ•¹¡¥Ñ•´™½È¥Ñ•´¥¸Á…”¥˜¥Í¥¹ÍÑ…¹”¡¥Ñ•´°‘¥Ð¤¤(€€€€€€€•±¥˜¥Í¥¹ÍÑ…¹”¡Á…”°‘¥Ð¤è(€€€€€€€€€€€É•ÍÕ±Ð¹…ÁÁ•¹¡Á…”¤(€€€É•ÑÕÉ¸É•ÍÕ±Ð(()‘•˜±…Ñ•ÍÑ}±•…Í•}…Ñ¥Ù¥Ñå}•Á½ ¡¹Õµ‰•Èè¥¹Ð¤€´ø¥¹Ðð9½¹”è(€€€ÑÉäè(€€€€€€€Á…•Ì€ô¡}©Í½¸ (€€€€€€€€€€€l‰…Á¤ˆ°€ˆ´µÁ…¥¹…Ñ”ˆ°€ˆ´µÍ±ÕÉÀˆ°˜‰É•Á½Ì½íIA=ô½¥ÍÍÕ•Ì½í¹Õµ‰•Éô½½µµ•¹ÑÌýÁ•É}Á…”ôÄÀÀ‰t(€€€€€€€€¤(€€€•á•ÁÐIÕ¹Ñ¥µ•ÉÉ½Èè(€€€€€€€É•ÑÕÉ¸9½¹”(€€€±…Ñ•ÍÐè¥¹Ðð9½¹”€ô9½¹”(€€€™½È½µµ•¹Ð¥¸™±…ÑÑ•¹}Á…•Ì¡Á…•Ì¤è(€€€€€€€¥˜½µµ•¹Ð¹•Ð ‰…ÕÑ¡½É}…ÍÍ½¥…Ñ¥½¸ˆ¤¹½Ð¥¸QIUMQ}MM=%Q%=9Lè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€‰½‘ä€ôÍÑÈ¡½µµ•¹Ð¹•Ð ‰‰½‘äˆ¤½È€ˆˆ¤(€€€€€€€™½ÈÁ…ÑÑ•É¸¥¸1M}Q%Y%Qe}AQQI9Lè(€€€€€€€€€€€™½Èµ…Ñ ¥¸Á…ÑÑ•É¸¹™¥¹‘…±°¡‰½‘ä¤è(€€€€€€€€€€€€€€€•Á½ €ô¥¹Ð¡µ…Ñ ¤(€€€€€€€€€€€€€€€±…Ñ•ÍÐ€ô•Á½ ¥˜±…Ñ•ÍÐ¥Ì9½¹”•±Í”µ…à¡±…Ñ•ÍÐ°•Á½ ¤(€€€É•ÑÕÉ¸±…Ñ•ÍÐ(()‘•˜…Ñ¥Ù•}™¥á•‘}Ý½É­•ÉÌ ¤€´øÍ•Ñm¥¹Ñtè(€€€Ý½É­•ÉÌèÍ•Ñm¥¹Ñt€ôÍ•Ð ¤(€€€ÉÕ¹Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åut€ômt(€€€™½ÈÍÑ…ÑÕÌ¥¸€ ‰ÅÕ•Õ•ˆ°€‰¥¹}ÁÉ½É•ÍÌˆ¤è(€€€€€€€Á…•Ì€ô¡}©Í½¸ (€€€€€€€€€€€l(€€€€€€€€€€€€€€€€‰…Á¤ˆ°(€€€€€€€€€€€€€€€€ˆ´µÁ…¥¹…Ñ”ˆ°(€€€€€€€€€€€€€€€€ˆ´µÍ±ÕÉÀˆ°(€€€€€€€€€€€€€€€˜‰É•Á½Ì½íIA=ô½…Ñ¥½¹Ì½Ý½É­™±½ÝÌ½™É•”µµ½‘•°µ™…Ñ½Éäµ•¹ÑÉä¹åµ°½ÉÕ¹ÌýÍÑ…ÑÕÌõíÍÑ…ÑÕÍô™Á•É}Á…”ôÄÀÀˆ°(€€€€€€€€€€€t(€€€€€€€€¤(€€€€€€€™½ÈÁ…”¥¸Á…•Ì½Èmtè(€€€€€€€€€€€¥˜¥Í¥¹ÍÑ…¹”¡Á…”°‘¥Ð¤è(€€€€€€€€€€€€€€€ÉÕ¹Ì¹•áÑ•¹¡Á…”¹•Ð ‰Ý½É­™±½Ý}ÉÕ¹Ìˆ°mt¤¤((€€€€Œ9•Ü•¹ÑÉäÉÕ¹Ì•¹½‘”Ñ¡”Ý½É­•È¥¸ÉÕ¸µ¹…µ”°Í¼•Ù•¸ÅÕ•Õ•ÉÕ¹Ì…É”(€€€€Œ…ÕÑ¡½É¥Ñ…Ñ¥Ù”‰•™½É”Ñ¡•¥È¡•…ÉÑ‰•…ÐÍÑ•À•á•ÕÑ•Ì¸(€€€Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘ÌèÍ•ÑmÍÑÉt€ôÍ•Ð ¤(€€€™½ÈÉÕ¸¥¸ÉÕ¹Ìè(€€€€€€€Ñ¥Ñ±”€ôÍÑÈ¡ÉÕ¸¹•Ð ‰‘¥ÍÁ±…å}Ñ¥Ñ±”ˆ¤½ÈÉÕ¸¹•Ð ‰¹…µ”ˆ¤½È€ˆˆ¤(€€€€€€€µ…Ñ €ôÉ”¹Í•…É ¡È‰q‰…Ñ½ÉåqÌ¬¡q¬¥qˆˆ°Ñ¥Ñ±”¤(€€€€€€€¥˜µ…Ñ è(€€€€€€€€€€€Ý½É­•ÉÌ¹…‘¡¥¹Ð¡µ…Ñ ¹É½ÕÀ Ä¤¤¤(€€€€€€€•±Í”è(€€€€€€€€€€€ÉÕ¹}¥€ôÍÑÈ¡ÉÕ¸¹•Ð ‰¥ˆ¤½È€ˆˆ¤(€€€€€€€€€€€¥˜ÉÕ¹}¥è(€€€€€€€€€€€€€€€Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ì¹…‘¡ÉÕ¹}¥¤((€€€¥˜Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ìè(€€€€€€€Á…•Ì€ô¡}©Í½¸ (€€€€€€€€€€€l‰…Á¤ˆ°€ˆ´µÁ…¥¹…Ñ”ˆ°€ˆ´µÍ±ÕÉÀˆ°˜‰É•Á½Ì½íIA=ô½¥ÍÍÕ•Ì¼ÄÀäÌ½½µµ•¹ÑÌýÁ•É}Á…”ôÄÀÀ‰t(€€€€€€€€¤(€€€€€€€™½È½µµ•¹Ð¥¸™±…ÑÑ•¹}Á…•Ì¡Á…•Ì¤è(€€€€€€€€€€€¥˜½µµ•¹Ð¹•Ð ‰…ÕÑ¡½É}…ÍÍ½¥…Ñ¥½¸ˆ¤¹½Ð¥¸QIUMQ}MM=%Q%=9Lè(€€€€€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€€€€€‰½‘ä€ôÍÑÈ¡½µµ•¹Ð¹•Ð ‰‰½‘äˆ¤½È€ˆˆ¤(€€€€€€€€€€€ÉÕ¹}µ…Ñ €ôÉ”¹Í•…É ¡Èˆ ý´¥yIÕ¸éqÌ¨¡q¬¥qÌ¨ˆ°‰½‘ä¤(€€€€€€€€€€€Ý½É­•É}µ…Ñ €ôÉ”¹Í•…É  (€€€€€€€€€€€€€€€Èˆ ý´¥y]½É­•ÈéqÌ©½Á•¹½‘”µ™É•”µµ½‘•°µ™…Ñ½Éä´¡q¬¥qÌ¨ˆ°‰½‘ä(€€€€€€€€€€€€¤(€€€€€€€€€€€¥˜ÉÕ¹}µ…Ñ …¹Ý½É­•É}µ…Ñ …¹ÉÕ¹}µ…Ñ ¹É½ÕÀ Ä¤¥¸Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ìè(€€€€€€€€€€€€€€€Ý½É­•ÉÌ¹…‘¡¥¹Ð¡Ý½É­•É}µ…Ñ ¹É½ÕÀ Ä¤¤¤(€€€€€€€€€€€€€€€Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ì¹‘¥Í…É¡ÉÕ¹}µ…Ñ ¹É½ÕÀ Ä¤¤((€€€¥˜Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ìè(€€€€€€€É…¥Í”IÕ¹Ñ¥µ•ÉÉ½È (€€€€€€€€€€€€‰Õ¹…‰±”Ñ¼É•Í½±Ù”Ý½É­•È¥‘•¹Ñ¥Ñä™½È…Ñ¥Ù”™¥á•µµ½‘•°ÉÕ¹Ìè€ˆ(€€€€€€€€€€€€¬€ˆ°€ˆ¹©½¥¸¡Í½ÉÑ•¡Õ¹É•Í½±Ù•‘}ÉÕ¹}¥‘Ì¤¤(€€€€€€€€¤(€€€É•ÑÕÉ¸Ý½É­•ÉÌ(()‘•˜½Ý¹•‘}Ñ…É•ÑÌ (€€€¥ÍÍÕ•Ìè±¥ÍÑm‘¥ÑmÍÑÈ°¹åutð9½¹”€ô9½¹”°(€€€ÁÉÌè±¥ÍÑm‘¥ÑmÍÑÈ°¹åutð9½¹”€ô9½¹”°(¤€´ø±¥ÍÑmÑÕÁ±•m¥¹Ð°ÍÑÉutè(€€€Ñ…É•ÑÌè±¥ÍÑmÑÕÁ±•m¥¹Ð°ÍÑÉut€ômt(€€€¥ÍÍÕ•}¥Ñ•µÌ€ô±¥ÍÑ}¥ÍÍÕ•Ì ¤¥˜¥ÍÍÕ•Ì¥Ì9½¹”•±Í”¥ÍÍÕ•Ì(€€€ÁÉ}¥Ñ•µÌ€ô±¥ÍÑ}ÁÉÌ ¤¥˜ÁÉÌ¥Ì9½¹”•±Í”ÁÉÌ(€€€™½È¥Ñ•´¥¸l©¥ÍÍÕ•}¥Ñ•µÌ°€©ÁÉ}¥Ñ•µÍtè(€€€€€€€½Ý¹•È€ô½Ý¹•É}½˜¡±…‰•±Í}½˜¡¥Ñ•´¤¤(€€€€€€€¥˜½Ý¹•È…¹½Ý¹•È€„ô€‰™…Ñ½ÉäéÕ¹½Ý¹•ˆè(€€€€€€€€€€€Ñ…É•ÑÌ¹…ÁÁ•¹ ¡¥¹Ð¡¥Ñ•µl‰¹Õµ‰•È‰t¤°½Ý¹•È¤¤(€€€É•ÑÕÉ¸Ñ…É•ÑÌ(()‘•˜É•½¹¥±•}ÍÑ…±•}±•…Í•Ì¡¹½Ý}•Á½ è¥¹Ðð9½¹”€ô9½¹”¤€´ø±¥ÍÑm¥¹Ñtè(€€€¹½Ý}•Á½ €ô¥¹Ð¡Ñ¥µ”¹Ñ¥µ” ¤¤¥˜¹½Ý}•Á½ ¥Ì9½¹”•±Í”¹½Ý}•Á½ (€€€€Œ…¥°±½Í•¥˜…Ñ¥Ù”µÉÕ¸‘¥Í½Ù•Éä¥Ì¥¹½µÁ±•Ñ”¸É•½¹¥±¥…Ñ¥½¸(€€€€Œ™…¥±ÕÉ”¥ÌÍ…™•ÈÑ¡…¸ÍÑ•…±¥¹œÝ½É¬™É½´„±¥Ù”•á•ÕÑ½È¸(€€€…Ñ¥Ù”€ô…Ñ¥Ù•}™¥á•‘}Ý½É­•ÉÌ ¤(€€€É•±•…Í•è±¥ÍÑm¥¹Ñt€ômt(€€€™½È¹Õµ‰•È°½Ý¹•È¥¸½Ý¹•‘}Ñ…É•ÑÌ ¤è(€€€€€€€…Ñ¥Ù¥Ñä€ô±…Ñ•ÍÑ}±•…Í•}…Ñ¥Ù¥Ñå}•Á½ ¡¹Õµ‰•È¤¥˜½Ý¹•È€ôô€‰™…Ñ½Éäé±½…°ˆ•±Í”9½¹”(€€€€€€€¥˜¹½Ð±•…Í•}¥Í}ÍÑ…±” (€€€€€€€€€€€½Ý¹•È°(€€€€€€€€€€€…Ñ¥Ù•}™¥á•‘}Ý½É­•ÉÌõ…Ñ¥Ù”°(€€€€€€€€€€€±…Ñ•ÍÑ}…Ñ¥Ù¥Ñå}•Á½ õ…Ñ¥Ù¥Ñä°(€€€€€€€€€€€¹½Ý}•Á½ õ¹½Ý}•Á½ °(€€€€€€€€¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É•Á±…•}™…Ñ½Éå}±…‰•±Ì¡¹Õµ‰•È°€‰™…Ñ½ÉäéÕ¹½Ý¹•ˆ¤(€€€€€€€É•±•…Í•¹…ÁÁ•¹¡¹Õµ‰•È¤(€€€€€€€ÁÉ¥¹Ð (€€€€€€€€€€€˜‰m™…Ñ½Éäµ½¹ÑÉ½±±•ÉtÉ•±•…Í•ÍÑ…±”í½Ý¹•Éô±•…Í”½¸€í¹Õµ‰•Éôˆ°(€€€€€€€€€€€™¥±”õÍåÌ¹ÍÑ‘•ÉÈ°(€€€€€€€€¤(€€€É•ÑÕÉ¸É•±•…Í•(()‘•˜Ý½É­•É}¡…Í}…Ñ¥Ù•}±•…Í”¡Ý½É­•ÈèÍÑÈ¤€´ø‰½½°è(€€€½Ý¹•È€ô˜‰™…Ñ½ÉäéíÝ½É­•Éôˆ(€€€É•ÑÕÉ¸…¹ä¡ÕÉÉ•¹Ñ}½Ý¹•È€ôô½Ý¹•È™½È|°ÕÉÉ•¹Ñ}½Ý¹•È¥¸½Ý¹•‘}Ñ…É•ÑÌ ¤¤(()‘•˜…ÍÍ¥¸¡Ý½É­•ÈèÍÑÈ¤€´ø…¹‘¥‘…Ñ”ð9½¹”è(€€€¥˜¹½ÐÉ”¹™Õ±±µ…Ñ ¡Èˆ üélØ´åuñlÄ´ÍulÀ´åuðÑlÀ´Ùt¤ˆ°Ý½É­•È¤è(€€€€€€€É…¥Í”MåÍÑ•µá¥Ð¡˜‰Õ¹ÍÕÁÁ½ÉÑ•™¥á•µµ½‘•°Ý½É­•ÈèíÝ½É­•Éôˆ¤((€€€€ŒÝ½É­•ÈÝ¥Ñ „±¥Ù”±•…Í”¥Ì…±É•…‘ä‰ÕÍä¸¼¹½ÐÅÕ•Õ”„Í•½¹Ñ…É•Ð(€€€€Œ‰•¡¥¹¥Ð…¹‘¼¹½ÐÉ•Ù¥Ù”…™™¥¹¥ÑäÑ¼Ñ¡”•á¥ÍÑ¥¹œÑ…É•Ð¸(€€€¥˜Ý½É­•É}¡…Í}…Ñ¥Ù•}±•…Í”¡Ý½É­•È¤è(€€€€€€€ÁÉ¥¹Ð (€€€€€€€€€€€˜‰m™…Ñ½Éäµ½¹ÑÉ½±±•Ét…Ñ½ÉäíÝ½É­•Éô…±É•…‘ä¡…Ì…¸…Ñ¥Ù”±•…Í”ìÍ­¥ÁÁ¥¹œ‘¥ÍÁ…Ñ ˆ°(€€€€€€€€€€€™¥±”õÍåÌ¹ÍÑ‘•ÉÈ°(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸9½¹”((€€€…¹‘¥‘…Ñ•Ì€ô‰Õ¥±‘}…¹‘¥‘…Ñ•Ì¡±¥ÍÑ}¥ÍÍÕ•Ì ¤°±¥ÍÑ}ÁÉÌ ¤¤(€€€™½È…¹‘¥‘…Ñ”¥¸…¹‘¥‘…Ñ•Ìè(€€€€€€€¥˜¹½Ð…¹‘¥‘…Ñ•}¥Í}±¥Ù•}•á•ÕÑ…‰±”¡…¹‘¥‘…Ñ”¤è(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜…ÍÍ¥¹}…¹‘¥‘…Ñ”¡…¹‘¥‘…Ñ”°Ý½É­•È¤è(€€€€€€€€€€€ÁÉ¥¹Ð (€€€€€€€€€€€€€€€˜‰m™…Ñ½Éäµ½¹ÑÉ½±±•Ét…ÍÍ¥¹•í…¹‘¥‘…Ñ”¹­¥¹‘ô€í…¹‘¥‘…Ñ”¹¹Õµ‰•Éô€ˆ(€€€€€€€€€€€€€€€˜‰±…¹”õí…¹‘¥‘…Ñ”¹±…¹•ôÁÉ¥½É¥Ñäõí…¹‘¥‘…Ñ”¹ÁÉ¥½É¥ÑåôÑ¼…Ñ½ÉäíÝ½É­•Éôˆ°(€€€€€€€€€€€€€€€™¥±”õÍåÌ¹ÍÑ‘•ÉÈ°(€€€€€€€€€€€€¤(€€€€€€€€€€€É•ÑÕÉ¸…¹‘¥‘…Ñ”(€€€É•ÑÕÉ¸9½¹”(()‘•˜É•±•…Í•}Ý½É­•È¡Ý½É­•ÈèÍÑÈ¤€´ø±¥ÍÑm¥¹Ñtè(€€€½Ý¹•È€ô˜‰™…Ñ½ÉäéíÝ½É­•Éôˆ(€€€É•±•…Í•è±¥ÍÑm¥¹Ñt€ômt(€€€™½È¹Õµ‰•È°ÕÉÉ•¹Ñ}½Ý¹•È¥¸½Ý¹•‘}Ñ…É•ÑÌ ¤è(€€€€€€€¥˜ÕÉÉ•¹Ñ}½Ý¹•È€„ô½Ý¹•Èè(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€É•Á±…•}™…Ñ½Éå}±…‰•±Ì¡¹Õµ‰•È°€‰™…Ñ½ÉäéÕ¹½Ý¹•ˆ¤(€€€€€€€É•±•…Í•¹…ÁÁ•¹¡¹Õµ‰•È¤(€€€É•ÑÕÉ¸É•±•…Í•(()‘•˜µ…¥¸ ¤€´ø¥¹Ðè(€€€Á…ÉÍ•È€ô…ÉÁ…ÉÍ”¹ÉÕµ•¹ÑA…ÉÍ•È ¤(€€€ÍÕ‰Á…ÉÍ•ÉÌ€ôÁ…ÉÍ•È¹…‘‘}ÍÕ‰Á…ÉÍ•ÉÌ¡‘•ÍÐô‰½µµ…¹ˆ°É•ÅÕ¥É•õQÉÕ”¤(€€€ÍÕ‰Á…ÉÍ•ÉÌ¹…‘‘}Á…ÉÍ•È ‰É•½¹¥±”ˆ¤((€€€…ÍÍ¥¹}Á…ÉÍ•È€ôÍÕ‰Á…ÉÍ•ÉÌ¹…‘‘}Á…ÉÍ•È ‰…ÍÍ¥¸ˆ¤(€€€…ÍÍ¥¹}Á…ÉÍ•È¹…‘‘}…ÉÕµ•¹Ð ˆ´µÝ½É­•Èˆ°É•ÅÕ¥É•õQÉÕ”¤((€€€É•±•…Í•}Á…ÉÍ•È€ôÍÕ‰Á…ÉÍ•ÉÌ¹…‘‘}Á…ÉÍ•È ‰É•±•…Í”ˆ¤(€€€É•±•…Í•}Á…ÉÍ•È¹…‘‘}…ÉÕµ•¹Ð ˆ´µÝ½É­•Èˆ°É•ÅÕ¥É•õQÉÕ”¤((€€€…ÉÌ€ôÁ…ÉÍ•È¹Á…ÉÍ•}…ÉÌ ¤((€€€¥˜…ÉÌ¹½µµ…¹€ôô€‰É•½¹¥±”ˆè(€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰É•±•…Í•ˆèÉ•½¹¥±•}ÍÑ…±•}±•…Í•Ì ¥ô¤¤(€€€€€€€É•ÑÕÉ¸€À((€€€¥˜…ÉÌ¹½µµ…¹€ôô€‰…ÍÍ¥¸ˆè(€€€€€€€…¹‘¥‘…Ñ”€ô…ÍÍ¥¸¡…ÉÌ¹Ý½É­•È¤(€€€€€€€¥˜…¹‘¥‘…Ñ”¥Ì9½¹”è(€€€€€€€€€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰­¥¹ˆè€‰¹½¹”‰ô¤¤(€€€€€€€€€€€É•ÑÕÉ¸€À(€€€€€€€ÁÉ¥¹Ð (€€€€€€€€€€€©Í½¸¹‘ÕµÁÌ (€€€€€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€€€€€‰­¥¹ˆè…¹‘¥‘…Ñ”¹­¥¹°(€€€€€€€€€€€€€€€€€€€€‰¹Õµ‰•Èˆè…¹‘¥‘…Ñ”¹¹Õµ‰•È°(€€€€€€€€€€€€€€€€€€€€‰±…¹”ˆè…¹‘¥‘…Ñ”¹±…¹”°(€€€€€€€€€€€€€€€€€€€€‰ÁÉ¥½É¥Ñäˆè…¹‘¥‘…Ñ”¹ÁÉ¥½É¥Ñä°(€€€€€€€€€€€€€€€€€€€€‰±¥¹­•‘}¥ÍÍÕ”ˆè…¹‘¥‘…Ñ”¹±¥¹­•‘}¥ÍÍÕ”°(€€€€€€€€€€€€€€€ô(€€€€€€€€€€€€¤(€€€€€€€€¤(€€€€€€€É•ÑÕÉ¸€À((€€€ÁÉ¥¹Ð¡©Í½¸¹‘ÕµÁÌ¡ì‰É•±•…Í•ˆèÉ•±•…Í•}Ý½É­•È¡…ÉÌ¹Ý½É­•È¥ô¤¤(€€€É•ÑÕÉ¸€À(()¥˜}}¹…µ•}|€ôô€‰}}µ…¥¹}|ˆè(€€€É…¥Í”MåÍÑ•µá¥Ð¡µ…¥¸ ¤¤(