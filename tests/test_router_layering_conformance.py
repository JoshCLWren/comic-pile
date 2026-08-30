"""Router/service/repository layering conformance tests.

House standard (AGENTS.md, "API Patterns"): routers validate input and call one
service; business logic lives in services; query construction and persistence
live in repositories (``app/repositories/``). Routers must not build SQL
queries or execute them against a session.

Legacy router modules still carry pre-existing violations that are being moved
out incrementally (tracker issue #1713; pilot trio thread/session/issue is
covered by issue #1692). This module enforces the standard as a shrink-only
ratchet:

- ``tests/router_layering_baseline.json`` records every module that currently
  violates the rule and which violation kinds it uses;
- any NEW violating module or NEW violation kind fails these tests;
- migrations must shrink or empty the baseline file.

These tests are intentionally dependency-free so the layering contract can be
checked without importing the application or touching a database.
"""

import ast
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROUTERS_DIR = REPOSITORY_ROOT / "app" / "api"
REPOSITORIES_PACKAGE = REPOSITORY_ROOT / "app" / "repositories"
AGENTS_MD_PATH = REPOSITORY_ROOT / "AGENTS.md"
BASELINE_PATH = Path(__file__).resolve().parent / "router_layering_baseline.json"

KIND_QUERY_IMPORT = "query-import"
KIND_EXECUTE_CALL = "execute-call"

#: SQLAlchemy names whose import constructs a SQL expression or configures a
#: query. Type-only imports (``AsyncSession``, ``JSONB``, ``IntegrityError``,
#: ...) are deliberately not listed.
QUERY_CONSTRUCTION_NAMES = frozenset(
    {
        "Select",
        "and_",
        "between",
        "case",
        "cast",
        "collate",
        "column",
        "contains_eager",
        "delete",
        "exists",
        "except_",
        "func",
        "immediateload",
        "insert",
        "intersect",
        "joinedload",
        "lazyload",
        "literal",
        "literal_column",
        "noload",
        "not_",
        "or_",
        "outerjoin",
        "raiseload",
        "select",
        "selectinload",
        "subqueryload",
        "table",
        "text",
        "tuple_",
        "undefer",
        "union",
        "union_all",
        "update",
    }
)

#: Session methods that execute a query. Flagged only when the receiver is
#: obviously a session/connection object to avoid matching result helpers such
#: as ``result.scalar()``.
QUERY_EXECUTION_METHODS = frozenset({"execute", "scalars", "scalar", "stream"})

_SESSION_RECEIVER_NAMES = {"conn", "db", "session"}


def _receiver_name(node: ast.AST) -> str | None:
    """Return the readable name of a call receiver, when available.

    Args:
        node: AST node of ``some.name`` attribute call receiver.

    Returns:
        The identifier name for simple receivers (``db``, ``self.session``),
        otherwise ``None``.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_session_receiver(node: ast.AST) -> bool:
    """Return whether a call receiver looks like a database session object.

    Args:
        node: AST node of the ``.<method>(...)`` call receiver.

    Returns:
        True when the receiver name is a known session alias.
    """
    name = _receiver_name(node)
    return name in _SESSION_RECEIVER_NAMES or bool(name and name.endswith("session"))


def scan_router_source(source: str) -> set[str]:
    """Scan one router module's source for layering violations.

    Args:
        source: Full Python source text of an ``app/api/`` module.

    Returns:
        The set of violation kinds present: ``query-import`` when a SQLAlchemy
        query constructor is imported, ``execute-call`` when a session executes
        a query directly.
    """
    kinds: set[str] = set()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_root = (node.module or "").split(".")[0]
            if module_root == "sqlalchemy":
                for alias in node.names:
                    if alias.name in QUERY_CONSTRUCTION_NAMES:
                        kinds.add(KIND_QUERY_IMPORT)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports_query_module = alias.name == "sqlalchemy" or alias.name.startswith(
                    ("sqlalchemy.sql", "sqlalchemy.dialects", "sqlalchemy.orm")
                )
                if imports_query_module:
                    kinds.add(KIND_QUERY_IMPORT)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in QUERY_EXECUTION_METHODS:
                if _is_session_receiver(func.value):
                    kinds.add(KIND_EXECUTE_CALL)

    return kinds


def load_baseline() -> dict[str, list[str]]:
    """Load the frozen violation baseline for legacy router modules.

    Returns:
        Mapping of router module name to its sorted violation kinds.
    """
    raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return {module: sorted(kinds) for module, kinds in raw.items()}


def current_router_violations() -> dict[str, list[str]]:
    """Compute today's layering violations across every router module.

    Returns:
        Mapping of violating router module name to its sorted violation kinds.
    """
    violations: dict[str, list[str]] = {}
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        kinds = sorted(scan_router_source(path.read_text(encoding="utf-8")))
        if kinds:
            violations[path.stem] = kinds
    return violations


def test_repositories_package_exists() -> None:
    """The repository layer must exist as the canonical home for queries."""
    assert REPOSITORIES_PACKAGE.is_dir()
    assert (REPOSITORIES_PACKAGE / "__init__.py").is_file()


def test_routers_add_no_new_layering_violations() -> None:
    """No router may introduce a new violation beyond the frozen baseline."""
    baseline = load_baseline()
    current = current_router_violations()

    growth: dict[str, list[str]] = {}
    for module, kinds in current.items():
        allowed = set(baseline.get(module, []))
        unexpected = [kind for kind in kinds if kind not in allowed]
        if unexpected:
            growth[module] = sorted(unexpected)

    assert not growth, (
        "Router modules introduced new layering violations; move query "
        "construction into app/repositories/ and business logic into "
        f"app/services/: {growth}"
    )


def test_layering_rule_is_codified_in_agents_md() -> None:
    """AGENTS.md must keep documenting the complete house layering standard.

    Enforces the full acceptance contract from tracker issue #1747: routers do
    validation plus exactly one service call, business logic lives in
    ``app/services/``, persistence in ``app/repositories/``, routers build no
    queries, and the MissingGreenlet extraction-before-commit rule is noted.
    """
    agents_md = AGENTS_MD_PATH.read_text(encoding="utf-8")

    assert "Router → Service → Repository" in agents_md
    assert "exactly one service call" in agents_md
    assert "**Services (`app/services/`)**" in agents_md
    assert "**Repositories (`app/repositories/`)**" in agents_md
    assert "No query construction" in agents_md
    assert "MissingGreenlet" in agents_md
    assert "extract model attributes BEFORE `await db.commit()`" in agents_md
    assert "tests/router_layering_baseline.json" in agents_md


def test_scanner_detects_violations_in_synthetic_router(tmp_path: Path) -> None:
    """The scanner flags query construction and execution in synthetic code."""
    violating = tmp_path / "violating.py"
    violating.write_text(
        "from sqlalchemy import select\n"
        "from sqlalchemy.orm import selectinload\n"
        "\n"
        "\n"
        "async def handler(db):\n"
        "    result = await db.execute(select(1))\n"
        "    return result\n",
        encoding="utf-8",
    )

    assert scan_router_source(violating.read_text(encoding="utf-8")) == {
        KIND_QUERY_IMPORT,
        KIND_EXECUTE_CALL,
    }


def test_scanner_accepts_compliant_router(tmp_path: Path) -> None:
    """Type-only SQLAlchemy imports and result helpers are not violations."""
    compliant = tmp_path / "compliant.py"
    compliant.write_text(
        "from sqlalchemy.exc import IntegrityError\n"
        "from sqlalchemy.ext.asyncio import AsyncSession\n"
        "\n"
        "from app.repositories.example import ExampleRepository\n"
        "\n"
        "\n"
        "async def handler(db: AsyncSession) -> None:\n"
        "    rows = await ExampleRepository(db).load_rows()\n"
        "    first = rows.scalar()\n"
        "    if first is None:\n"
        "        raise IntegrityError('stmt', {}, Exception('missing'))\n",
        encoding="utf-8",
    )

    assert scan_router_source(compliant.read_text(encoding="utf-8")) == set()
