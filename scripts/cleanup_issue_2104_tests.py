from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

MOCK_PATTERNS = (
    r"\nvi\.mock\('\.\./hooks/useContinuityReadiness', \(\) => \(\{.*?\n\}\)\)\)\n",
    r"\nvi\.mock\('\.\./pages/RollPage/components/ContinuityReadinessSummary', \(\) => \(\{.*?\n\}\)\)\)\n",
)

for relative in [
    "frontend/src/unit/RatingView.copy.test.tsx",
    "frontend/src/unit/RatingViewContinuity.test.tsx",
    "frontend/src/unit/ReadingContextPillar.typography.test.tsx",
    "frontend/src/unit/ReadingContextPillar.test.tsx",
    "frontend/src/unit/RatingView.context-presence.test.tsx",
    "frontend/src/unit/ReadingContextPillar.navigation.test.tsx",
]:
    path = ROOT / relative
    if not path.exists():
        continue
    content = path.read_text()
    original = content
    for pattern in MOCK_PATTERNS:
        content = re.sub(pattern, "\n", content, flags=re.DOTALL)
    if content != original:
        path.write_text(content)
        print(f"cleaned {relative}")

print("remaining readiness references:")
for base in [ROOT / "app", ROOT / "frontend" / "src", ROOT / "tests"]:
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".json"}:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if any(
            needle in text
            for needle in (
                "/continuity/readiness",
                "api-continuity-readiness",
                "useContinuityReadiness",
                "ContinuityReadiness",
                "PlanReadiness",
                "/readiness",
            )
        ):
            print(path.relative_to(ROOT))
