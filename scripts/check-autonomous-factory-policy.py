#!/usr/bin/env python3
"""Fail when autonomous factory policy files drift on critical invariants."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docs/AUTONOMOUS_FACTORY_POLICY.md"
PROTOCOL = ROOT / "docs/ISSUE_EXECUTION_PROTOCOL.md"
SCHEDULED_PROMPT = ROOT / "docs/CHATGPT_FACTORY_PROMPT.md"
ENTRYPOINT = ROOT / "scripts/comic-pile-opencode-factory.sh"
HEARTBEAT_ENTRYPOINT = ROOT / "scripts/comic-pile-opencode-factory-heartbeat.sh"
NEXT_TASK_PROMPT = ROOT / "prompts/agent-next-task.md"
ISSUE_SKILL = ROOT / ".agents/skills/github-issue-kanban/SKILL.md"
LEGACY_PIPELINE = ROOT / "scripts/opencode_pipeline.sh"


def require(text: str, needle: str, source: Path) -> None:
    """Require one invariant string in a policy source.

    Args:
        text: Complete source text to inspect.
        needle: Required invariant text.
        source: Source path used in the failure message.

    Returns:
        None.
    """
    if needle not in text:
        raise SystemExit(f"{source}: missing required policy text: {needle!r}")


def forbid(text: str, needle: str, source: Path) -> None:
    """Reject one known contradictory policy string.

    Args:
        text: Complete source text to inspect.
        needle: Forbidden contradictory text.
        source: Source path used in the failure message.

    Returns:
        None.
    """
    if needle in text:
        raise SystemExit(f"{source}: forbidden policy drift found: {needle!r}")


def validate_texts(policy: str, protocol: str, entrypoint: str) -> None:
    """Validate all factory control-plane texts against canonical invariants.

    Args:
        policy: Canonical autonomous factory policy text.
        protocol: GitHub issue execution protocol text.
        entrypoint: Combined local factory wrappers and scheduled prompt text.

    Returns:
        None.
    """
    for needle in (
        "Version: 19",
        "Every product, behavior, deployment, operational, or factory-tooling PR must update",
        "exactly one isolated Markdown fragment",
        "`docs/changelog.md` is the frozen historical archive",
        "Changelog: not user-facing",
        "A missing required changelog entry is an actionable review defect",
        "Drive the open issue backlog to zero",
        "An empty or blocked ordinary backlog is never an idle condition",
        "If no ordinary executable issue can be selected, do not declare the factory idle.",
        "Blocked work never authorizes a worker to pause or disable itself.",
        "Never pause, disable, suspend, or stop a scheduled factory because the ordinary backlog is blocked or empty.",
        "The newest unclaimed open issue labeled both `user-reported` and `bug`.",
        "The highest-priority unclaimed reproducible E2E-discovered `bug` issue.",
        "When fewer than four substantive implementation PRs are open",
        "At most one implementation worker may own an issue",
        "Existing open PRs are not automatically higher priority than unclaimed issues.",
        "fetch review submissions and all current inline review threads",
        "ignore only clearly non-actionable status noise",
        "classify every actionable finding as fixed, demonstrably outdated",
        "A worker's own review conclusion does not silently override existing human or bot feedback.",
        "Workers may merge a PR without asking again only after all of these gates are satisfied",
        "the worker supplies the exact expected head SHA",
        "Never enable auto-merge.",
        "Issue #679 is excluded from ordinary executable-backlog selection",
        "restore the maintained Chromium Playwright CI suite",
        "create one focused issue per independent reproducible product defect",
        "preserve `user-reported` only for bugs actually reported by a user",
        "Firefox and WebKit may be run manually",
        "Never push directly to `main`.",
        "Never create or convert a draft PR unless Josh explicitly requests a draft.",
        "## Durable resume packet",
        "<!-- factory-resume:v1 -->",
        "one full label-set replacement",
        "Never implement a transition as separate remove-then-add calls",
    ):
        require(policy, needle, POLICY)

    for marker in (
        "comic-pile-factory-implement-claim-v3",
        "comic-pile-factory-implement-progress-v3",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-review-v2:<sha>:pass",
        "changes-required",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-fix-progress-v3",
        "comic-pile-factory-ready-v2",
        "factory-resume:v1",
        "comic-pile-factory-needs-human-v2",
        "comic-pile-factory-claim-released-v3",
    ):
        require(policy, marker, POLICY)

    for obsolete in (
        "HONEST STAGE FAST PATH",
        "Planning PRs are encouraged",
        "Always split large PRs into stages",
        "A heartbeat may stop after one substantive commit",
        "Do not start a new issue while an owned issue has executable remaining work.",
        "Prefer finishing already-started issues over starting new ones.",
        "ready PR awaiting Josh's explicit merge authorization",
        "Never merge.",
        "Never merge or enable auto-merge without Josh explicitly authorizing that merge.",
        "full configured end-to-end test coverage",
        "full configured E2E matrix",
        "repair the backlog in the current PR rather than recording only the worker's own change",
    ):
        forbid(policy, obsolete, POLICY)

    for needle in (
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "Never create a draft pull request unless Josh explicitly requests a draft.",
        "Before pass, readiness, or merge, inspect the exact current head SHA",
        "An unresolved actionable correctness, security, ownership, data-integrity, migration, concurrency, recovery, or test-validity finding blocks readiness and merge.",
        "green on every required check",
        "free of unresolved actionable review findings",
        "The merge operation must include the exact expected head SHA.",
        "Never enable auto-merge.",
        "Autonomous factory workers may merge",
    ):
        require(protocol, needle, PROTOCOL)

    for obsolete in (
        "Autonomous factory workers may merge whenever CI is green.",
        "Autonomous factory workers may ignore unresolved review findings.",
        "Autonomous factory workers must wait for Josh's explicit authorization for every merge.",
        "Auto-merge may be enabled after CI starts.",
    ):
        forbid(protocol, obsolete, PROTOCOL)

    for needle in (
        "docs/AUTONOMOUS_FACTORY_POLICY.md",
        "Drive the open issue backlog to zero",
        "Treat the generated changelog as part of the completion contract",
        "docs/changelog.d/YYYY-MM-DD-<pr-number>.md",
        "Changelog: not user-facing",
        "newest unclaimed open issue labeled both `user-reported` and `bug`",
        "reproducible E2E-discovered",
        "fewer than four substantive implementation PRs",
        "fetch all current-SHA review submissions and inline review threads",
        "ignore only status noise, summaries, release notes, rate-limit notices",
        "classify every actionable finding as fixed, demonstrably outdated",
        "exact expected head SHA",
        "Never enable auto-merge",
        "Issue #679 is deferred",
        "Chromium Playwright E2E suite",
        "Create one GitHub issue per independent reproducible Chromium product defect",
        "Firefox and WebKit are optional diagnostics",
        "Never create or convert a draft PR unless Josh explicitly",
        "Never treat an empty or blocked backlog as a reason to idle, pause, disable yourself, or stop checking.",
        "Only Josh may pause or disable this factory.",
        "comic-pile-factory-review-claim-v2",
        "comic-pile-factory-fix-claim-v3",
        "comic-pile-factory-ready-v2",
    ):
        require(entrypoint, needle, ENTRYPOINT)

    for obsolete in (
        "open a truthful draft PR",
        "mark a draft ready when",
        "HONEST STAGE FAST PATH",
        "Prefer finishing already-started issues over starting new ones.",
        "Do not start a new issue while an owned issue has executable remaining work.",
        "ready PR awaiting Josh's explicit merge authorization",
        "Never merge.",
        "Never merge or enable auto-merge without Josh explicitly authorizing that merge.",
        "merge the pull request after CI",
        "merge whenever CI is green",
        "ignore unresolved review threads",
        "full configured E2E matrix",
        "Firefox + WebKit + Chromium",
        "Treat docs/changelog.md as part of the completion contract",
        "core.hooksPath=/dev/null",
        "commit even if tests are not fully passing",
        "commit even if not fully passing",
    ):
        forbid(entrypoint, obsolete, ENTRYPOINT)


def validate_local_guidance() -> None:
    """Validate every local and scheduled factory entry point independently.

    Returns:
        None.
    """
    for source in (SCHEDULED_PROMPT, HEARTBEAT_ENTRYPOINT, NEXT_TASK_PROMPT, ISSUE_SKILL):
        text = source.read_text(encoding="utf-8")
        require(text, "factory-resume:v1", source)

    scheduled = SCHEDULED_PROMPT.read_text(encoding="utf-8")
    require(scheduled, "Version: 19", SCHEDULED_PROMPT)
    require(scheduled, "one full atomic label-set replacement", SCHEDULED_PROMPT)

    next_task = NEXT_TASK_PROMPT.read_text(encoding="utf-8")
    require(next_task, "only\n  after the PR merges", NEXT_TASK_PROMPT)

    issue_skill = ISSUE_SKILL.read_text(encoding="utf-8")
    require(issue_skill, "After the PR merges", ISSUE_SKILL)

    legacy = LEGACY_PIPELINE.read_text(encoding="utf-8")
    forbid(legacy, "core.hooksPath=/dev/null", LEGACY_PIPELINE)
    forbid(legacy, "commit even if tests are not fully passing", LEGACY_PIPELINE)
    forbid(legacy, "commit even if not fully passing", LEGACY_PIPELINE)


def read_entrypoint_text() -> str:
    """Read local orchestration prompts and the scheduled ChatGPT prompt template.

    Returns:
        The combined wrapper, heartbeat, and scheduled prompt source text.
    """
    return "\n".join(
        (
            ENTRYPOINT.read_text(encoding="utf-8"),
            HEARTBEAT_ENTRYPOINT.read_text(encoding="utf-8"),
            SCHEDULED_PROMPT.read_text(encoding="utf-8"),
        )
    )


def main() -> None:
    """Read checked-in policy sources and validate their alignment.

    Returns:
        None.
    """
    validate_texts(
        POLICY.read_text(encoding="utf-8"),
        PROTOCOL.read_text(encoding="utf-8"),
        read_entrypoint_text(),
    )
    validate_local_guidance()
    print("Autonomous factory policy invariants are aligned.")


if __name__ == "__main__":
    main()
