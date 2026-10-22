"""Issue-level acceptance evidence for exact-head factory approvals."""

import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from typing import Any

PREFIX = "FACTORY_ACCEPTANCE_V1="
HEADINGS = ("scope", "implementation required", "requirements", "acceptance", "verification before", "required evidence", "completion evidence", "expected behavior", "outcome")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")


def requirements(body: str) -> list[str]:
    """Preserve every issue requirement, including unrecognized headings and prose.

    Args:
        body: Complete authoritative issue body.

    Returns:
        Ordered paragraphs and bullets with their heading context.

    Raises:
        ValueError: If the issue provides no reviewable requirement text.
    """
    section = "Issue"
    entries: list[str] = []
    current: list[str] = []

    def flush() -> None:
        """Finish an entry without losing continuation lines."""
        if current:
            entries.append(f"{section}: {' '.join(current)}")
            current.clear()

    for source in body.splitlines():
        line = source.strip()
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        heading = HEADING.match(source)
        if heading:
            flush()
            section = heading.group(1).strip()
            continue
        if not line:
            flush()
            continue
        item = BULLET.match(source)
        if item:
            flush()
            line = re.sub(r"^\[[ xX]\]\s*", "", item.group(1)).strip()
        if line:
            current.append(line)
    flush()
    if not entries:
        raise ValueError("Issue has no reviewable criteria, clarification required")
    return entries


def digest(body: str) -> str:
    """Return SHA-256 of the full issue body, including all revisions."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def marker(issue: int, head: str, body: str) -> str:
    """Return a dedicated, whole-comment exact-head issue-revision marker."""
    return (
        "<!-- comic-pile-factory-acceptance-v1:"
        f"issue-{issue}:head-{head}:digest-{digest(body)} -->"
    )


def attested(controller_comments: Iterable[str], issue: int, head: str, body: str) -> bool:
    """Accept only an entire controller-bot comment matching the expected marker.

    Args:
        controller_comments: Complete comment bodies prefiltered to trusted controller bot.
        issue: Linked issue number.
        head: Exact reviewed head.
        body: Unmodified authoritative issue body.

    Returns:
        Whether the controller emitted a standalone attestation comment.
    """
    expected = marker(issue, head, body)
    return any(comment.strip() == expected for comment in controller_comments)


def report_from_text(review_text: str) -> Mapping[str, Any] | None:
    """Read one structured acceptance report from the full reviewer log."""
    lines = [line[len(PREFIX):] for line in review_text.splitlines()
             if line.startswith(PREFIX)]
    if len(lines) != 1 or len(lines[0]) > 2000000:
        return None
    try:
        data = json.loads(lines[0])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def validate(report: Mapping[str, Any] | None, issue: int, head: str, body: str, changed_paths: Iterable[str]) -> list[str]:
    """Return specific errors; zero errors authorizes an acceptance marker."""
    if report is None:
        return ["missing or malformed FACTORY_ACCEPTANCE_V1 report"]
    if report.get("issue") != issue or report.get("head") != head:
        return ["report refers to a different issue or head"]
    if report.get("issue_digest") != digest(body):
        return ["issue requirements changed during review; require fresh review"]
    items = report.get("items")
    rubric = requirements(body)
    if not isinstance(items, list) or len(items) != len(rubric):
        return [f"report must cover all {len(rubric)} issue criteria"]
    changed = set(changed_paths)
    seen, errors = set(), []
    for item in items:
        if not isinstance(item, dict):
            errors.append("criterion must be a structured object")
            continue
        name = item.get("id")
        if (not isinstance(name, str) or
                name not in {f"A{i}" for i in range(1, len(rubric) + 1)} or
                name in seen):
            errors.append(f"invalid/duplicate criterion {name!r}")
            continue
        seen.add(name)
        if item.get("status") != "pass":
            errors.append(f"{name}: missing PASS evidence")
        if item.get("file") not in changed:
            errors.append(f"{name}: cite a file changed by this PR")
        evidence = item.get("evidence")
        if not isinstance(evidence, str) or len(evidence.strip()) < 30:
            errors.append(f"{name}: give specific implementation evidence")
        test = item.get("test")
        if not isinstance(test, str) or len(test.strip()) < 12 or test.lower().strip() in {
            "not tested", "tests passed", "no tests", "not needed"
        }:
            errors.append(f"{name}: name the test/check and what it verifies")
    if len(seen) != len(rubric):
        errors.append("not every criterion was evaluated")
    return errors


def rubric(body: str) -> str:
    """Render numbered acceptance requirements without dropping prose."""
    return "\n".join(f"A{i}: {item}" for i, item in enumerate(requirements(body), 1))



CLOSING_RE = re.compile(
    r"(?i)\b(?:closes?|closed|fix(?:es|ed)?|resolves?|resolved)\s+#(\d+)"
)
BRANCH_RE = re.compile(r"^factory/\d+-(\d+)-")


def linked_issue(branch: str, body: str) -> int | None:
    """Resolve a linked issue using the same semantics as the controller.

    Args:
        branch: PR branch name.
        body: PR description.

    Returns:
        Canonical linked issue number, if a supported link was found.
    """
    match = BRANCH_RE.match(branch)
    if match:
        return int(match.group(1))
    match = CLOSING_RE.search(body)
    return int(match.group(1)) if match else None


def mission(issue: int, head: str, body: str) -> str:
    """Provide all requirements and current revision to the reviewer.

    Args:
        issue: Linked issue number.
        head: Reviewed PR commit SHA.
        body: Exact authoritative issue body.

    Returns:
        Review instructions and required structured report schema.
    """
    revision = digest(body)
    return (
        f"\nISSUE ACCEPTANCE: #{issue}, head {head}, issue digest {revision}.\n"
        "Review every numbered requirement below against the real diff and tests."
        " Do not approve when any requirement is missing or unverified."
        " Before FACTORY_GATE_READY output exactly one single-line JSON record"
        " with every criterion represented:\n"
        f'{PREFIX}{{"issue":{issue},"head":"{head}",'
        f'"issue_digest":"{revision}","items":['
        '{"id":"A1","status":"pass","file":"changed/path.py",'
        '"evidence":"Concrete inspected implementation behavior",'
        '"test":"Executable command and observed result"}]}\n'
        "Use A1 through the last criterion. Missing/unverified means REPAIR.\n"
        + rubric(body)
    )

if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["rubric"]:
            print(rubric(sys.stdin.read()))
        elif sys.argv[1:] == ["resolve"]:
            data = json.load(sys.stdin)
            number = linked_issue(
                str(data.get("headRefName") or ""),
                str(data.get("body") or ""),
            )
            if number is None:
                raise ValueError("PR has no supported linked issue")
            print(number)
        elif len(sys.argv) == 4 and sys.argv[1] == "mission":
            data = json.load(sys.stdin)
            if not isinstance(data.get("body"), str):
                raise ValueError("issue body missing")
            print(mission(int(sys.argv[2]), sys.argv[3], data["body"]))
        else:
            raise ValueError("usage: rubric | resolve | mission ISSUE HEAD")
    except (ValueError, TypeError, KeyError) as exc:
        print(f"acceptance input unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
