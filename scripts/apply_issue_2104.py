from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content)


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    content = read(path)
    found = content.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} occurrences, found {found}: {old[:80]!r}")
    write(path, content.replace(old, new, count))


def sub(path: str, pattern: str, replacement: str, *, count: int = 1) -> None:
    content = read(path)
    updated, found = re.subn(pattern, replacement, content, count=count, flags=re.DOTALL)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} regex matches, found {found}: {pattern[:100]!r}")
    write(path, updated)


def remove(path: str) -> None:
    target = ROOT / path
    if not target.exists():
        raise RuntimeError(f"missing expected file: {path}")
    target.unlink()


# Backend router and product-only public contracts.
replace("app/api/__init__.py", "from app.api import continuity_readiness as continuity_readiness\n", "")
replace("app/api/__init__.py", "dependency.router.include_router(continuity_readiness.router)\n", "")
replace("app/api/__init__.py", '    "continuity_readiness",\n', "")

# Preserve plan compiler mechanics that were accidentally hosted in a readiness module.
replace(
    "app/services/continuity_plan_writer.py",
    "from app.continuity_plan_readiness import _detect_plan_cycles, plan_rule_marker\n",
    "",
)
writer_marker = "from app.schemas.continuity_rule import ContinuityNodeType\n\n\nasync def validate_node_ownership("
writer_helpers = '''from app.schemas.continuity_rule import ContinuityNodeType\n\n\nPLAN_RULE_MARKER_PREFIX = "continuity-plan"\n\n\ndef plan_rule_marker(plan_id: int) -> str:\n    """Return the durable ownership marker for rules compiled from one plan."""\n    return f"{PLAN_RULE_MARKER_PREFIX}:{plan_id}"\n\n\ndef _detect_plan_cycles(\n    nodes: list[tuple[str, int]],\n    edges: list[tuple[tuple[str, int], tuple[str, int]]],\n) -> set[tuple[str, int]]:\n    """Return every plan node participating in a directed cycle."""\n    adjacency: dict[tuple[str, int], list[tuple[str, int]]] = {node: [] for node in nodes}\n    for source, target in edges:\n        if source in adjacency and target in adjacency:\n            adjacency[source].append(target)\n    for target_list in adjacency.values():\n        target_list.sort()\n\n    color: dict[tuple[str, int], int] = dict.fromkeys(nodes, 0)\n    in_cycle: set[tuple[str, int]] = set()\n\n    for start_node in sorted(nodes):\n        if color[start_node] != 0:\n            continue\n\n        stack: list[tuple[tuple[str, int], int]] = [(start_node, 0)]\n        path: list[tuple[str, int]] = []\n\n        while stack:\n            node, state = stack.pop()\n            if state == 0:\n                if color[node] in {1, 2}:\n                    continue\n                color[node] = 1\n                path.append(node)\n                stack.append((node, 1))\n                for nxt in reversed(adjacency.get(node, ())):\n                    if color[nxt] == 0:\n                        stack.append((nxt, 0))\n                    elif color[nxt] == 1:\n                        try:\n                            idx = path.index(nxt)\n                            in_cycle.update(path[idx:])\n                        except ValueError:\n                            pass\n            else:\n                if path and path[-1] == node:\n                    path.pop()\n                color[node] = 2\n\n    return in_cycle\n\n\nasync def validate_node_ownership('''
replace("app/services/continuity_plan_writer.py", writer_marker, writer_helpers)

# Reading Plan CRUD keeps compiler ownership markers but loses the readiness endpoint.
replace(
    "app/api/continuity_plan.py",
    "from app.continuity_plan_readiness import evaluate_plan_readiness, plan_rule_marker\n",
    "",
)
replace(
    "app/api/continuity_plan.py",
    "from app.services.continuity_plan_writer import (\n    replace_compiled_rules,\n    validate_node_ownership,\n)",
    "from app.services.continuity_plan_writer import (\n    plan_rule_marker,\n    replace_compiled_rules,\n    validate_node_ownership,\n)",
)
replace("app/api/continuity_plan.py", "    ContinuityPlanReadinessResponse,\n", "")
sub(
    "app/api/continuity_plan.py",
    r'\n@router\.get\(\n    "/continuity-plans/\{plan_id\}/readiness",.*?\n\n@router\.put\(',
    "\n\n@router.put(",
)

# Remove readiness-only schemas from the plan contract.
replace("app/schemas/continuity_plan.py", "from app.schemas.continuity_readiness import ContinuityBlocker\n\n", "")
sub(
    "app/schemas/continuity_plan.py",
    r'PlanReadinessDiagnosticCode = Literal\[.*?\]\n\n',
    "",
)
plan_schema = read("app/schemas/continuity_plan.py")
cut = plan_schema.find("\nclass ContinuityPlanChainNode(BaseModel):")
if cut < 0:
    raise RuntimeError("plan readiness schema tail not found")
write("app/schemas/continuity_plan.py", plan_schema[:cut].rstrip() + "\n")

# Crossover detail keeps factual/project data and no longer evaluates global readiness.
replace("app/api/dependency_group.py", "\nfrom app.continuity_readiness import evaluate_continuity_readiness\n", "")
replace(
    "app/api/dependency_group.py",
    "        The group payload with enriched members, readiness, and linked plans.\n",
    "        The group payload with enriched members and linked plans.\n",
)
sub(
    "app/api/dependency_group.py",
    r'\n    # Evaluate continuity readiness for crossover\n    readiness = await evaluate_continuity_readiness\(.*?\n\n    # Fetch linked plans',
    "\n    # Fetch linked plans",
)
replace("app/api/dependency_group.py", "        readiness=readiness,\n", "")
replace("app/schemas/dependency_group.py", "from app.schemas.continuity_readiness import ContinuityReadinessResponse\n", "")
replace(
    "app/schemas/dependency_group.py",
    '    """Full crossover detail with enriched members, readiness, and linked plans."""\n',
    '    """Full crossover detail with enriched members and linked plans."""\n',
)
replace("app/schemas/dependency_group.py", "    readiness: ContinuityReadinessResponse | None = None\n", "")

# Preserve blocked-state proof while removing assertions against the deleted second verdict.
sub(
    "tests/test_continuity_blocked_state.py",
    r'\n    readiness_response = await auth_client\.post\(\n        "/api/v1/continuity/readiness",.*?assert readiness_response\.json\(\)\["is_readable"\] is False\n',
    "\n",
)
replace(
    "tests/test_continuity_plan_writer_service.py",
    "from app.continuity_plan_readiness import plan_rule_marker\n",
    "from app.services.continuity_plan_writer import plan_rule_marker\n",
)

# Internal chain traversal remains supported. Tests import its shared snapshot directly.
chain_test = ROOT / "tests/test_continuity_readiness_chains.py"
if chain_test.exists():
    content = chain_test.read_text()
    content = content.replace(
        "from app.continuity_readiness import SNAPSHOT_SESSION_KEY, _load_snapshot",
        "from app.services.continuity_graph import SNAPSHOT_SESSION_KEY, load_snapshot as _load_snapshot",
    )
    chain_test.write_text(content)

# Frontend public clients/hooks/query keys.
replace("frontend/src/hooks/index.ts", "export { useContinuityChains } from './useContinuityChains'\n", "")
replace(
    "frontend/src/hooks/index.ts",
    "export { useContinuityReadiness, type ContinuityReadinessState } from './useContinuityReadiness'\n",
    "",
)
sub(
    "frontend/src/query/queryKeys.ts",
    r'  continuity: \{\n.*?\n  \},\n',
    "",
)
sub(
    "frontend/src/query/queryKeys.ts",
    r'  plans: \{\n.*?\n  \},\n',
    "",
)

# Reading context keeps factual prerequisite edges, never a second eligibility verdict.
replace("frontend/src/pages/RollPage/components/ReadingContextPillar.tsx", "import { ContinuityReadinessSummary } from './ContinuityReadinessSummary'\n", "")
replace("frontend/src/pages/RollPage/components/ReadingContextPillar.tsx", "import { useContinuityReadiness } from '../../../hooks/useContinuityReadiness'\n", "")
replace("frontend/src/pages/RollPage/components/ReadingContextPillar.tsx", "  const readinessState = useContinuityReadiness(issueId)\n", "")
replace("frontend/src/pages/RollPage/components/ReadingContextPillar.tsx", "      <ContinuityReadinessSummary issueId={issueId} readinessState={readinessState} />\n\n", "")
replace("frontend/src/pages/RollPage/components/ReadingContextPillar.tsx", "          readinessState={readinessState}\n", "")

replace("frontend/src/pages/RollPage/components/ReadingPathPanel.tsx", "import type { ContinuityReadinessState } from '../../../hooks/useContinuityReadiness'\n", "")
replace("frontend/src/pages/RollPage/components/ReadingPathPanel.tsx", "  readinessState: ContinuityReadinessState\n", "")
replace("frontend/src/pages/RollPage/components/ReadingPathPanel.tsx", "  readinessState,\n", "")
sub(
    "frontend/src/pages/RollPage/components/ReadingPathPanel.tsx",
    r'\n  const blockerLabels = useMemo\(\(\) => \{.*?\n  const readinessResolved =.*?readinessState\.readiness !== null\n',
    "\n",
)
sub(
    "frontend/src/pages/RollPage/components/ReadingPathPanel.tsx",
    r'\n      \{readinessResolved && readinessState\.readiness\?\.is_readable && \(.*?\n      \)\}\n\n      \{readinessResolved && readinessState\.readiness && !readinessState\.readiness\.is_readable && \(.*?\n      \)\}\n',
    "\n",
)

# Planner no longer calls a plan-readiness endpoint to fill display labels.
replace("frontend/src/pages/ContinuityPlannerPage.tsx", "        let hydrated = hydrateLabels(\n", "        const hydrated = hydrateLabels(\n")
sub(
    "frontend/src/pages/ContinuityPlannerPage.tsx",
    r'        const needsBatch = hydrated\.some\(.*?\n        \}\n        if \(!active\) return',
    "        if (!active) return",
)

# Remove plan readiness types/client method.
replace("frontend/src/services/api-continuity-plans.ts", "import type { ContinuityBlocker, UnreadIssueDetail } from './api-continuity-readiness'\n", "")
sub(
    "frontend/src/services/api-continuity-plans.ts",
    r'\nexport type PlanReadinessDiagnosticCode =.*?\nexport type \{ ContinuityBlocker, UnreadIssueDetail \}\n',
    "\n",
)
sub(
    "frontend/src/services/api-continuity-plans.ts",
    r'  readiness: \(planId: number\): Promise<ContinuityPlanReadinessResponse> =>\n    api\.get<ContinuityPlanReadinessResponse>\(`\/v1\/continuity-plans\/\$\{planId\}\/readiness`\),\n',
    "",
)

# Crossover detail presents progress/membership/plan facts only.
replace("frontend/src/services/api-dependency-groups.ts", "import type { ContinuityReadinessResponse } from './api-continuity-readiness'\n", "")
replace("frontend/src/services/api-dependency-groups.ts", "  readiness: ContinuityReadinessResponse | null\n", "")
replace("frontend/src/pages/CrossoverDetailPage.tsx", "import type { ContinuityReadinessResponse, ContinuityBlocker } from '../services/api-continuity-readiness'\n", "")
sub("frontend/src/pages/CrossoverDetailPage.tsx", r'\ninterface BlockedMember \{.*?\n\}\n', "\n")
replace("frontend/src/pages/CrossoverDetailPage.tsx", "  const [readiness, setReadiness] = useState<ContinuityReadinessResponse | null>(null)\n", "")
replace("frontend/src/pages/CrossoverDetailPage.tsx", "      setReadiness(detail.readiness ?? null)\n", "")
sub(
    "frontend/src/pages/CrossoverDetailPage.tsx",
    r'\n  const blockedMembers = readiness\?\.blockers\.flatMap\(.*?\n  const blockedMemberMap = new Map\(blockedMembers\.map\(b => \[b\.membershipId, b\]\)\)\n',
    "\n",
)
sub(
    "frontend/src/pages/CrossoverDetailPage.tsx",
    r'\n      \{readiness && \(.*?\n      \)\}\n\n      \{nextUnread && \(',
    "\n      {nextUnread && (",
)
replace("frontend/src/pages/CrossoverDetailPage.tsx", "                const blockedInfo = blockedMemberMap.get(member.membership.id)\n", "")
sub(
    "frontend/src/pages/CrossoverDetailPage.tsx",
    r"                  className=\{'flex items-center gap-3 rounded-lg p-3 transition-colors ' \+ \(\n                    blockedInfo\n                      \? 'bg-\[var\(--theme-danger\)\]/10 border border-\[var\(--theme-danger\)\]/40'\n                      : isRead\n                      \? 'bg-\[var\(--theme-bg-panel\)\] border border-\[var\(--theme-border\)\]'\n                      : 'bg-\[var\(--theme-continuity-accent\)\]/10 border border-\[var\(--theme-continuity-accent\)\]/30'\n                  \)\}",
    "                  className={'flex items-center gap-3 rounded-lg p-3 transition-colors ' + (isRead\n                    ? 'bg-[var(--theme-bg-panel)] border border-[var(--theme-border)]'\n                    : 'bg-[var(--theme-continuity-accent)]/10 border border-[var(--theme-continuity-accent)]/30'\n                  )}",
)
sub(
    "frontend/src/pages/CrossoverDetailPage.tsx",
    r'\n                      \{blockedInfo && \(.*?\n                      \)\}',
    "",
    count=2,
)

# Remove readiness-only compatibility files and their dedicated unit tests.
for path in [
    "app/api/continuity_readiness.py",
    "app/continuity_readiness.py",
    "app/schemas/continuity_readiness.py",
    "app/continuity_plan_readiness.py",
    "frontend/src/services/api-continuity-readiness.ts",
    "frontend/src/hooks/useContinuityReadiness.ts",
    "frontend/src/hooks/useContinuityChains.ts",
    "frontend/src/pages/RollPage/components/ContinuityReadinessSummary.tsx",
    "frontend/src/components/PlanReadinessPanel.tsx",
    "frontend/src/unit/useContinuityReadiness.test.ts",
    "frontend/src/unit/useContinuityReadiness.test.tsx",
    "frontend/src/unit/useContinuityChains.test.tsx",
    "frontend/src/unit/PlanReadinessPanel.test.tsx",
    "tests/test_continuity_readiness_api.py",
]:
    remove(path)

print("Applied #2104 product-surface removal")
