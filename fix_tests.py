#!/usr/bin/env python3
"""Fix E2E tests for PR #345 - Update thread card clicks to use mobile menu button."""

import re

# Files to fix
files_to_fix = [
    "frontend/src/test/dependencies.spec.ts",
    "frontend/src/test/roll.spec.ts",
    "frontend/src/test/migration.spec.ts",
    "frontend/src/test/issue-282-neutral-rating-default.spec.ts",
    "frontend/src/test/issue-286-snooze-d20-feedback.spec.ts",
    "frontend/src/test/issue-292-snoozed-offset-badge.spec.ts",
]

# Patterns to replace
replacements = [
    # Pattern 1: Click on thread h3 to open action sheet - replace with ⋮ button click
    (
        r"(// Click on the thread title to open action sheet.*?\n)(.*?\.locator\('#queue-container \.glass-card h3'\)\s*\.filter\(\{ hasText: ['\"]([^'\"]+)['\"] \}\)\s*\.click\(\))",
        r"""\1// Click the ⋮ menu button to open action sheet
await authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: '\3' }).locator('button[aria-label="Open actions"]').click()""",
    ),
    # Pattern 2: Click on thread element (in roll.spec.ts) - replace with ⋮ button click
    (
        r"(// Click on snoozed thread to open action sheet.*?\n)(await snoozedThreadElement\.click\(\))",
        r"""\1// Click the ⋮ menu button to open action sheet
await authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: snoozedThreadName }).locator('button[aria-label="Open actions"]').click()""",
    ),
    # Pattern 3: Click on thread element (in roll.spec.ts, non-snoozed) - replace with ⋮ button click
    (
        r"(// Click on thread to open action sheet.*?\n)(await threadElement\.click\(\))",
        r"""\1// Click the ⋮ menu button to open action sheet
await authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: threadName }).locator('button[aria-label="Open actions"]').click()""",
    ),
    # Pattern 4: Click on first thread (in issue files)
    (
        r"(// Click on the first thread to open action sheet.*?\n)(.*?\.locator\('#queue-container \.glass-card'\)\.first\(\)\.click\(\))",
        r"""\1// Click the ⋮ menu button to open action sheet
await page.locator('#queue-container .glass-card').first().locator('button[aria-label="Open actions"]').click()""",
    ),
    # Pattern 5: Click on thread title in migration (click on thread title)
    (
        r"(// Click on the thread to open action sheet.*?\n)(.*?\.locator\('#queue-container \.glass-card'\)\.filter\(\{ hasText: threadTitle \}\)\.first\(\)\.click\(\))",
        r"""\1// Click the ⋮ menu button to open action sheet
await authenticatedPage.locator('#queue-container .glass-card').filter({ hasText: threadTitle }).locator('button[aria-label="Open actions"]').click()""",
    ),
]

for file_path in files_to_fix:
    try:
        with open(file_path) as f:
            content = f.read()

        original_content = content

        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content, flags=re.DOTALL)

        if content != original_content:
            with open(file_path, "w") as f:
                f.write(content)
            print(f"✓ Fixed {file_path}")
        else:
            print(f"  No changes needed for {file_path}")

    except FileNotFoundError:
        print(f"✗ File not found: {file_path}")
    except Exception as e:
        print(f"✗ Error processing {file_path}: {e}")

print("\nDone!")
