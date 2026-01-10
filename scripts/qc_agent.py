#!/usr/bin/env python3
"""Quality Control Agent for Ralph Orchestrator.

Reviews Ralph-completed tasks for quality before marking as done.
Works autonomously like Ralph - no questions, just iteration.
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class QualityCheck:
    """Quality check results for a task."""

    def __init__(self) -> None:
        """Initialize quality check state."""
        self.passed = True
        self.issues = []
        self.test_coverage = 0.0
        self.lint_errors = 0
        self.code_quality_findings = []
        self.edge_case_issues = []
        self.general_hacks = []


def run_pytest() -> tuple[bool, str, float]:
    """Run pytest with coverage.

    Returns:
        Tuple of (passed, output, coverage_percent)
    """
    logger.info("Running pytest...")
    try:
        result = subprocess.run(
            ["pytest", "--cov=comic_pile", "--cov-report=term-missing", "-q"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        output = result.stdout + result.stderr
        coverage = 0.0
        for line in output.split("\n"):
            if "TOTAL" in line and "coverage" in line.lower():
                try:
                    coverage_str = line.split("coverage")[1].split("%")[0].strip()
                    coverage = float(coverage_str)
                except Exception:
                    pass

        passed = result.returncode == 0
        return passed, output, coverage
    except subprocess.TimeoutExpired:
        return False, "Tests timed out", 0.0
    except Exception as e:
        return False, str(e), 0.0


def run_lint() -> tuple[bool, str]:
    """Run linting script.

    Returns:
        Tuple of (passed, output)
    """
    logger.info("Running lint...")
    try:
        result = subprocess.run(
            ["bash", "scripts/lint.sh"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Linting timed out"
    except Exception as e:
        return False, str(e)


def generate_review_comment(
    task_title: str, task_id: int, qc: QualityCheck, test_output: str, lint_output: str
) -> str:
    """Generate a quality control review comment.

    Args:
        task_title: Task title
        task_id: Task ID
        qc: Quality check results
        test_output: Pytest output
        lint_output: Linting output

    Returns:
        Review comment text
    """
    lines = [
        f"## Quality Control Review for {task_id}",
        "",
        f"**Task:** {task_title}",
        f"**Reviewed at:** {datetime.now(UTC).isoformat()}",
        "",
        "### Test Coverage",
        f"**Result: {'✓ PASSED' if qc.passed else '✗ FAILED'}",
        f"**Coverage:** {qc.test_coverage:.1f}%",
        "",
    ]

    if test_output:
        lines.append(f"```\n{test_output}\n```")

    if qc.code_quality_findings:
        lines.extend(["", "### Code Quality Findings"])
        lines.extend([f"- {f}" for f in qc.code_quality_findings])

    if qc.edge_case_issues:
        lines.extend(["", "### Edge Case Issues"])
        lines.extend([f"- {f}" for f in qc.edge_case_issues])

    if qc.general_hacks:
        lines.extend(["", "### Hacks and Workarounds"])
        lines.extend([f"- {f}" for f in qc.general_hacks])

    lines.extend(
        [
            "",
            "### Quality Decision",
        ]
    )

    if qc.passed:
        lines.extend(
            [
                "✅ **APPROVED** - Code meets quality standards.",
                "",
                "No additional iteration needed. Marking as done.",
            ]
        )
    else:
        lines.extend(
            [
                "❌ **REJECTED** - Code does not meet quality standards.",
                "",
                "Please address the issues above and resubmit for review.",
            ]
        )

    return "\n".join(lines)


def main() -> None:
    """Run the quality control agent."""
    parser = argparse.ArgumentParser(description="Quality Control Agent for Ralph Orchestrator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show review without marking issues",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="JoshCLWren/comic-pile",
        help="GitHub repository",
    )
    args = parser.parse_args()

    logger.info("Starting Quality Control Agent")

    logger.info("Finding in-review tasks on GitHub...")
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                args.repo,
                "--label",
                "ralph-status:in-review",
                "--json",
                "number,title,body",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        tasks = json.loads(result.stdout)
    except Exception as e:
        logger.error(f"Failed to find in-review tasks: {e}")
        sys.exit(1)

    if not tasks:
        logger.info("No in-review tasks found. Nothing to review.")
        return

    logger.info(f"Found {len(tasks)} in-review task(s)")

    for task in tasks:
        task_id = task["number"]
        task_title = task["title"]
        logger.info(f"Reviewing task #{task_id}: {task_title}")

        qc = QualityCheck()

        test_passed, test_output, test_coverage = run_pytest()
        qc.test_coverage = test_coverage

        if not test_passed:
            qc.passed = False
            qc.issues.append("Tests failed")

        lint_passed, lint_output = run_lint()
        if not lint_passed:
            qc.passed = False
            qc.issues.append("Linting failed")
            if lint_output:
                qc.lint_errors += lint_output.count("error")

        if lint_passed and test_passed:
            qc.code_quality_findings = []

        review_comment = generate_review_comment(task_title, task_id, qc, test_output, lint_output)

        if args.dry_run:
            logger.info(f"[DRY RUN] Review for task #{task_id}")
            print("\n" + "=" * 60)
            print(review_comment)
            print("=" * 60 + "\n")
            continue

        logger.info(f"Posting review comment to issue #{task_id}")
        try:
            subprocess.run(
                ["gh", "issue", "comment", str(task_id), "--body", review_comment],
                check=True,
            )
            logger.info(f"Review comment posted to #{task_id}")
        except Exception as e:
            logger.error(f"Failed to post comment: {e}")
            continue

        if qc.passed:
            logger.info(f"Task #{task_id} APPROVED - marking as done")
            try:
                subprocess.run(
                    [
                        "gh",
                        "issue",
                        "edit",
                        str(task_id),
                        "--remove-label",
                        "ralph-status:in-review",
                        "--add-label",
                        "ralph-status:done",
                    ],
                    check=False,
                )
            except Exception as e:
                logger.error(f"Failed to update status: {e}")
        else:
            logger.info(f"Task #{task_id} REJECTED")
            qc_issue_title = f"QC-FAIL-{task_id}: Quality issues in {task_title}"

            qc_issue_body = f"""**Original Task:** #{task_id} - {task_title}

**Review Findings:**

{review_comment}

**Action Required:**

Please address the issues above and resubmit for quality control review.
"""

            try:
                subprocess.run(
                    [
                        "gh",
                        "issue",
                        "create",
                        "--title",
                        qc_issue_title,
                        "--label",
                        "ralph-task",
                        "--label",
                        "qc-issue",
                        "--label",
                        "ralph-priority:high",
                        "--label",
                        "ralph-status:pending",
                        "--body",
                        qc_issue_body,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                logger.info("Created QC issue")

                subprocess.run(
                    [
                        "gh",
                        "issue",
                        "edit",
                        str(task_id),
                        "--remove-label",
                        "ralph-status:in-review",
                        "--add-label",
                        "ralph-status:pending",
                    ],
                    check=False,
                )
                logger.info("Created QC issue")

                subprocess.run(
                    [
                        "gh",
                        "issue",
                        "edit",
                        str(task_id),
                        "--remove-label",
                        "ralph-status:in-review",
                        "--add-label",
                        "ralph-status:pending",
                    ],
                    check=True,
                )
            except Exception as e:
                logger.error(f"Failed to create QC issue: {e}")

        logger.info("-" * 60)

    logger.info("Quality Control complete")


if __name__ == "__main__":
    main()
