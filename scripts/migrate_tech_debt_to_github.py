#!/usr/bin/env python3
"""Migrate TECH_DEBT.md items to GitHub Issues."""

import os
import re
import subprocess
from pathlib import Path


def read_tech_debt() -> str:
    """Read TECH_DEBT.md content."""
    debt_file = Path(__file__).parent.parent / "TECH_DEBT.md"
    with open(debt_file) as f:
        return f.read()


def get_item_priority(content: str, item_number: int) -> str:
    """Determine priority based on position in file."""
    # Count lines to find which section we're in
    lines = content.split("\n")

    # Find position of this item
    item_pattern = rf"### {item_number}\."
    for i, line in enumerate(lines):
        if re.match(item_pattern, line):
            # Look backward to find the section header
            for j in range(i, -1, -1):
                if j < 0:
                    break
                if lines[j].startswith("## Critical Priority"):
                    return "critical"
                elif lines[j].startswith("## High Priority"):
                    return "high"
                elif lines[j].startswith("## Medium Priority"):
                    return "medium"
                elif lines[j].startswith("## Low Priority"):
                    return "low"

    return "medium"  # Default


def extract_item_details(content: str, item_number: int) -> dict:
    """Extract details for a single debt item."""
    # Find to section for this item
    item_pattern = rf"^### {item_number}\. (.+)$"
    match = re.search(item_pattern, content, re.MULTILINE)

    if not match:
        return None

    title = match.group(1)
    priority = get_item_priority(content, item_number)

    # Extract content after the header
    start_pos = match.end()

    # Find next section or end of file
    next_section = re.search(r"\n### \d+\. ", content[start_pos:])
    if next_section:
        end_pos = start_pos + next_section.start()
    else:
        end_pos = len(content)

    item_content = content[start_pos:end_pos]

    # Extract details from content
    details = {
        "number": item_number,
        "title": title,
        "priority": priority,
        "description": "",
        "why_debt": "",
        "location": "",
        "approach": "",
        "effort": "Unknown",
    }

    current_field = None
    for line in item_content.split("\n"):
        if "**Location:**" in line:
            details["location"] = line.replace("**Location:**", "").strip("` ")
        elif "**Description:**" in line:
            details["description"] = line.replace("**Description:**", "").strip()
            current_field = "description"
        elif "**Why It's Debt:**" in line or "**Why It Is Debt:**" in line:
            details["why_debt"] = line.split(":", 1)[1].strip()
            current_field = "why_debt"
        elif "**Suggested Approach:**" in line:
            details["approach"] = line.split(":", 1)[1].strip()
            current_field = "approach"
        elif "**Estimated Effort:**" in line:
            details["effort"] = line.split(":", 1)[1].strip()
        elif current_field and line.strip() and not line.startswith("**"):
            if current_field == "description":
                details["description"] += " " + line.strip()
            elif current_field == "why_debt":
                details["why_debt"] += " " + line.strip()
            elif current_field == "approach":
                details["approach"] += " " + line.strip()

    return details


def priority_to_github(priority: str) -> str:
    """Convert priority to GitHub label."""
    mapping = {
        "critical": "ralph-priority:critical",
        "high": "ralph-priority:high",
        "medium": "ralph-priority:medium",
        "low": "ralph-priority:low",
    }
    return mapping.get(priority, "ralph-priority:medium")


def create_github_issue(item: dict, dry_run: bool = False) -> str | None:
    """Create GitHub issue for a debt item."""
    task_id = f"DEBT-{item['number']:03d}"
    title = f"{task_id}: {item['title'][:60]}"

    priority_label = priority_to_github(item["priority"])
    status_label = "ralph-status:pending"
    labels = ["ralph-task", "code-debt", priority_label, status_label]

    # Build issue body
    body_parts = [
        f"**Task ID:** `{task_id}`",
        f"**Priority:** {item['priority'].upper()}",
        f"**Status:** pending",
        f"**Type:** code_debt",
        "",
        "## Description",
        item["description"],
        "",
        "## Why It's Debt",
        item["why_debt"],
    ]

    if item["location"]:
        body_parts.extend(["", "## Location", f"```", item["location"], f"```"])

    if item["approach"]:
        body_parts.extend(["", "## Suggested Approach", item["approach"]])

    body_parts.extend(["", f"**Estimated Effort:** {item['effort']}"])

    body = "\n".join(body_parts)

    if dry_run:
        print(f"[DRY RUN] Would create issue:")
        print(f"  Title: {title}")
        print(f"  Priority: {item['priority']}")
        print(f"  Labels: {', '.join(labels)}")
        print()
        return None

    # Create issue using gh CLI
    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        title,
        "--body",
        body,
        "--repo",
        os.getenv("GITHUB_REPO", "JoshCLWren/comic-pile"),
    ]
    for label in labels:
        cmd.extend(["--label", label])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        issue_url = result.stdout.strip()
        print(f"✓ Created: {title}")
        print(f"  Priority: {item['priority']}")
        print(f"  URL: {issue_url}")
        return issue_url
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create: {title}")
        print(f"  Error: {e.stderr}")
        return None


def main() -> None:
    """Main migration function."""
    import argparse

    parser = argparse.ArgumentParser(description="Migrate TECH_DEBT.md items to GitHub Issues")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be created without creating issues"
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="JoshCLWren/comic-pile",
        help="GitHub repository (default: JoshCLWren/comic-pile)",
    )
    args = parser.parse_args()

    os.environ["GITHUB_REPO"] = args.repo

    print("Reading TECH_DEBT.md...")
    content = read_tech_debt()

    # Find all item numbers
    item_numbers = re.findall(r"### (\d+)\.", content)

    print(f"Found {len(item_numbers)} debt items\n")

    if not item_numbers:
        print("No debt items found. Nothing to migrate.")
        return

    print("=" * 60)
    created_count = 0

    for item_str in item_numbers:
        item_num = int(item_str)
        item = extract_item_details(content, item_num)

        if not item:
            print(f"Skipping item {item_num} - could not parse")
            continue

        print(f"Item {item_num}: {item['title'][:50]}")

        url = create_github_issue(item, dry_run=args.dry_run)
        if url:
            created_count += 1

        print("-" * 60)

    print("\n" + "=" * 60)
    if not args.dry_run:
        print(f"Migration complete! Created {created_count}/{len(item_numbers)} issues.")
        print("\nNext steps:")
        print("  1. Verify issues at: https://github.com/JoshCLWren/comic-pile/issues")
        print("  2. Work on issues based on priority")
        print("  3. Close items as they're completed")
    else:
        print("Dry run complete. No issues created.")
        print("Run without --dry-run to create issues.")


if __name__ == "__main__":
    main()
