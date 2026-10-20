# Strict mypy typing policy (Phase 0)

This document records the intentional ComicPile typing-policy differences
from mypy's stock `strict = true` preset. It is the authoritative reference
for Phase 1+ migration workers: every override below is narrow and documented,
and there are no blanket per-module ignores or broad error-code disables.

## Why this document exists

Issue #3075 (strict-mypy epic) and its Phase 0 child #3250 require that
ComicPile's existing typing opinions stay authoritative. Strict mypy does
not get to redefine them. Where strict mypy conflicts with an intentional
repo policy, the override is configured explicitly in the repository mypy
configuration and recorded here so it is visible rather than hidden in a
broad ignore. `pyproject.toml` (`[tool.mypy]`) is canonical: every ratchet
and inventory command passes it explicitly. `mypy.ini` mirrors the strict
profile for ad-hoc `mypy` runs.

## The three deliberate deviations

### 1. `disallow_any_generics`

Mypy's strict preset requires explicit type arguments on every generic
(`dict`, `list`, `set`, ...). ComicPile's earlier policy permitted `Any` in
specific, reviewed places and tolerated bare generics when the element type is
genuinely dynamic. The migrated surface now inherits strict mypy's enabled
setting.

**Status:** enabled for strict-clean modules. The `type-arg` errors in the
Phase 0 inventory are local typing cleanup, not design problems. Each is
fixed by narrowing the element type at the call site, not by suppressing the
check. Genuinely dynamic payloads name their wire contract instead of falling
back to `dict[str, Any]`: undo-snapshot thread and issue states are typed with
`SnapshotThreadState` / `SnapshotIssueState` in
`app/services/snapshot_contract.py`, so a strict-clean module describes the
fields it reads and never hides them behind `Any`.

### 2. `disallow_subclassing_any`

Strict mypy flags subclassing a class whose type is `Any`. ComicPile has
several framework-adjacent base classes (repository bases, service mixins)
whose runtime type is dynamic by design.

**Status:** enabled. No migrated module relies on a per-module relaxation to
escape strictness; any future finding here is a design/interface review, not
a local annotation cleanup.

### 3. `disallow_untyped_calls`

Strict mypy errors on calling an untyped function. ComicPile has a large
legacy surface (scripts, archive utilities) that is intentionally not under
the strict migration. Calling into it from strict-clean modules is acceptable
only where the resolved definition is typed; remaining `no-untyped-call`
findings are migration work, not a blanket allowance.

**Status:** enabled. Strict-clean modules must annotate their own definitions,
and they may not depend on untyped calls.

## What is NOT allowed

- Blanket `# type: ignore` comments. The pre-commit hook blocks them.
- Broad per-module error-code disables in `mypy.ini` (e.g.
  `[mypy-app.roll] disallow_untyped_defs = False`). The only per-module
  sections in `mypy.ini` are third-party packages without stubs.
- Fake precision: replacing legitimate `Any` usage with unsafe casts,
  sprawling protocols, or invented types purely to satisfy the checker.
- Disabling `warn_redundant_casts`, `warn_unused_ignores`, or
  `warn_return_any`. These stay on.

## Third-party stub boundary

`mypy.ini` carries extensive third-party overrides (sqlalchemy, fastapi,
pydantic, asyncpg, jose, bcrypt, slowapi, httpx, Pillow, and others); `pyproject.toml`
only adds `pytest` and `sqlalchemy` overrides plus
`disallow_untyped_decorators = false` for `tests.test_mypy_baseline`. The
profiles do not mirror each other: `pyproject.toml` is the narrower ratchet
configuration and `mypy.ini` is the broader ad-hoc reference. Both restrict
overrides to deliberate categories—`pyproject.toml` to third-party stubs plus
the single test-module decorator exception—so contributors know which settings
the gate uses.

Each entry is deliberate: the package genuinely has no stubs, and the import
boundary is typed by hand at the call site. This is not a suppression of
typing work; it is the standard mypy mechanism for untyped dependencies,
and it is listed explicitly so it is reviewable.

## Ratchet semantics

A module is "strict-clean" when strict mypy reports zero errors for it under
this configuration. The ratchet baseline is `mypy-clean.json`: an explicit,
nonempty list of exact file paths inside the Python surface. The set grows
monotonically; no module escapes the ratchet through new ignores, config
exclusions, or dropped manifest entries.

Commands:

- `make mypy-check` runs `scripts/mypy_baseline.py check`, fails on any
  diagnostic in a listed path, and is the local gate for this ratchet;
- `make mypy-inventory` runs the same checker and refreshes
  `docs/typing/mypy-inventory.json`, the full migration inventory; and
- `tests/test_mypy_baseline.py` guards the manifest validation, clean-scope
  failure behavior, and package coverage.

`app.repositories` was migrated to strict-clean in #3410; it is the first
production package whose every module is ratcheted.
