"""Guard the generated OpenAPI schema as the only frontend transport authority.

Every transport shape the React client sends or receives must come from
``frontend/src/generated/openapi.json``. A handwritten ``interface`` or inline
``type ... = {`` object that reuses a generated component-schema name silently
becomes a second, drifting authority for the same wire contract.

The repository still carries known duplicates from the pre-#4457 frontend. They
are frozen in ``tests/frontend_server_contract_types_baseline.json``: this guard
fails when a new duplicate appears, and also fails when a baseline entry is no
longer present so the inventory can only shrink. View models that legitimately
narrow or project a transport shape must be written as aliases derived from
``components['schemas'][...]`` (see ``Issue``/``IssueListResponse`` in
``frontend/src/types/index.ts``), not as standalone object literals.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
FRONTEND_SOURCE: Final = REPO_ROOT / "frontend" / "src"
GENERATED_CLIENT: Final = FRONTEND_SOURCE / "generated" / "openapi.json"
BASELINE: Final = Path(__file__).with_name("frontend_server_contract_types_baseline.json")

_DECLARATION: Final = re.compile(
    r"^export\s+(?:interface\s+(?P<interface>[A-Za-z_][A-Za-z0-9_]*)"
    r"|type\s+(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<shape>[^\n]*))",
    re.MULTILINE,
)
_OBJECT_SHAPE_PREFIX: Final = "{"


def _generated_schema_names() -> frozenset[str]:
    """Return every component-schema name in the checked-in generated client.

    Returns:
        The generated OpenAPI component-schema names.
    """
    document: dict[str, object] = json.loads(GENERATED_CLIENT.read_text(encoding="utf-8"))
    components = document.get("components")
    if not isinstance(components, dict):
        raise AssertionError("generated OpenAPI document has no components mapping")
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        raise AssertionError("generated OpenAPI document has no component schemas")
    return frozenset(name for name in schemas if isinstance(name, str))


def _declared_object_type_names(source: str) -> list[str]:
    """List frontend type names declared as standalone object shapes.

    Args:
        source: TypeScript source text of one frontend module.

    Returns:
        Names of ``export interface`` declarations and ``export type`` aliases
        whose right-hand side starts with an inline object literal. Aliases that
        derive their shape from ``components['schemas'][...]`` are not included.
    """
    names: list[str] = []
    for match in _DECLARATION.finditer(source):
        interface_name = match.group("interface")
        if interface_name is not None:
            names.append(interface_name)
            continue
        shape = match.group("shape") or ""
        alias_name = match.group("alias")
        if alias_name is not None and shape.lstrip().startswith(_OBJECT_SHAPE_PREFIX):
            names.append(alias_name)
    return names


def _handwritten_transport_declarations() -> dict[str, list[str]]:
    """Map each frontend module to its duplicate generated-schema declarations.

    Returns:
        Repository-relative module paths mapped to the sorted declaration names
        that reuse a generated component-schema name as a handwritten shape.
    """
    schema_names = _generated_schema_names()
    duplicates: dict[str, list[str]] = {}
    for path in sorted(FRONTEND_SOURCE.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if "generated" in path.relative_to(FRONTEND_SOURCE).parts:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        declared = _declared_object_type_names(path.read_text(encoding="utf-8"))
        duplicate_names = sorted({name for name in declared if name in schema_names})
        if duplicate_names:
            duplicates[relative] = duplicate_names
    return duplicates


def _load_baseline() -> dict[str, list[str]]:
    """Read the shrink-only duplicate inventory.

    Returns:
        Repository-relative module paths mapped to sorted frozen duplicate names.
    """
    raw: dict[str, list[str]] = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {path: sorted(names) for path, names in raw.items()}


def test_no_new_handwritten_duplicate_server_contract_types() -> None:
    """Fail when a new handwritten type reuses a generated schema name."""
    baseline = _load_baseline()
    current = _handwritten_transport_declarations()
    added: list[str] = []
    for path, names in sorted(current.items()):
        allowed = set(baseline.get(path, []))
        added.extend(f"{path}: {name}" for name in names if name not in allowed)
    assert added == [], (
        "New handwritten duplicate(s) of generated OpenAPI schemas:\n  "
        + "\n  ".join(added)
        + "\nAlias the generated schema instead, e.g. "
        "`export type Name = components['schemas']['Name']`, or derive a "
        "documented view model from it (see Issue in frontend/src/types/index.ts)."
    )


def test_baseline_does_not_retain_migrated_duplicates() -> None:
    """Fail when the baseline lists a duplicate that no longer exists."""
    baseline = _load_baseline()
    current = _handwritten_transport_declarations()
    stale: list[str] = []
    for path, names in sorted(baseline.items()):
        remaining = set(current.get(path, []))
        stale.extend(f"{path}: {name}" for name in names if name not in remaining)
    assert stale == [], (
        "Stale entries in tests/frontend_server_contract_types_baseline.json:\n  "
        + "\n  ".join(stale)
        + "\nRemove them: the duplicate inventory is shrink-only."
    )


def test_issue_transport_family_uses_generated_authority() -> None:
    """Keep the #4457 Issue migration on the generated schema authority."""
    types_source = (FRONTEND_SOURCE / "types" / "index.ts").read_text(encoding="utf-8")
    assert "components['schemas']['IssueResponse']" in types_source, (
        "Issue must stay derived from the generated IssueResponse schema"
    )
    assert "components['schemas']['IssueListResponse']" in types_source, (
        "IssueListResponse must stay derived from the generated IssueListResponse schema"
    )
    declared = _handwritten_transport_declarations().get("frontend/src/types/index.ts", [])
    assert "Issue" not in declared
    assert "IssueListResponse" not in declared
