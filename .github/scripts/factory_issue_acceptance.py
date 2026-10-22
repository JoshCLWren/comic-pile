"""Issue-level acceptance evidence for exact-head factory approvals."""

import hashlib
import json
import re
import sys

PREFIX = "FACTORY_ACCEPTANCE_V1="
HEADINGS = ("scope", "implementation required", "requirements", "acceptance", "verification before", "required evidence", "completion evidence", "expected behavior", "outcome")
HEADING = re.compile(r"^#{2,4}\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")


def requirements(body):
    active, found = False, []
    for line in body.splitlines():
        heading = HEADING.match(line)
        if heading:
            active = heading.group(1).lower().strip().startswith(HEADINGS)
            continue
        if not active:
            continue
        item = BULLET.match(line)
        if not item:
            continue
        value = re.sub(r"^\[[ xX]\]\s*", "", item.group(1)).strip()
        if value and not re.match(r"^(?:#\d+|Depends on #)", value, re.I) and value not in found:
            found.append(value)
    if found:
        return found
    return ["Complete the issue's requested behavior and acceptance criteria"]


def digest(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def marker(issue, head, body):
    return (
        "<!-- comic-pile-factory-acceptance-v1:"
        f"issue-{issue}:head-{head}:digest-{digest(body)} -->"
    )


def attested(controller_comments, issue, head, body):
    expected = marker(issue, head, body)
    return any(expected in [line.strip() for line in comment.splitlines()]
               for comment in controller_comments)


def report_from_text(review_text):
    lines = [line[len(PREFIX):] for line in review_text.splitlines()
             if line.startswith(PREFIX)]
    if len(lines) != 1 or len(lines[0]) > 60000:
        return None
    try:
        data = json.loads(lines[0])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def validate(report, issue, head, body, changed_paths):
    """Return specific errors; zero errors authorizes an acceptance marker."""
    if report is None:
        return ["missing or malformed FACTORY_ACCEPTANCE_V1 report"]
    if report.get("issue") != issue or report.get("head") != head:
        return ["report refers to a different issue or head"]
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


def rubric(body):
    return "\n".join(f"A{i}: {item}" for i, item in enumerate(requirements(body), 1))


if __name__ == "__main__":
    if sys.argv[1:] != ["rubric"]:
        raise SystemExit("Usage: factory_issue_acceptance.py rubric")
    print(rubric(sys.stdin.read()))
