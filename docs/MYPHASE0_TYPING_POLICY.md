# Strict mypy typing policy (Phase 0)

This document records the intentional ComicPile typing-policy differences
from mypy's stock `strict = true` preset. It is the authoritative reference
for Phase 1+ migration workers: every override below is narrow and documented,
and there are no blanket per-module ignores or broad error-code disables.

## Why this document exists

Issue #3075 (strict-mypy epic) and its Phase 0 child #3250 require that
ComicPile's existing typing opinions stay authoritative. Strict mypy does
not get to redefine them. Where strict mypy conflicts with an intentional
repo policy, the override is configured explicitly in `mypy.ini` and recorded
here so it is visible rather than hidden in a broad ignore.

## The three deliberate deviations

### 1. `disallow_any_generics = False`

Mypy's strict preset requires explicit type arguments on every generic
(`dict`, `list`, `set`, ...). ComicPile's intentional policy (enforced by
`scripts/lint.sh`) permits `Any` in specific, reviewed places and treats
bare generics as acceptable when the element type is genuinely dynamic.

**Status:** kept as `False` for Phase 0. The `type-arg` errors in the Phase 0
inventory are local typing cleanup, not design problems. Each is fixed by
narrowing the element type at the call site, not by suppressing the check.

### 2. `disallow_subclassing_any = False`

Strict mypy flags subclassing a class whose type is `Any`. ComicPile has
several framework-adjacent base classes (repository bases, service mixins)
whose runtime type is dynamic by design.

**Status:** kept as `False`. No migrated module relies on this to escape
strictness; it is a baseline allowance for framework glue that Phase 1+
will narrow per-module.

### 3. `disallow_untyped_calls = False`

Strict mypy errors on calling an untyped function. ComicPile has a large
legacy surface (scripts, archive utilities) that is intentionally not under
the strict migration. Calling into it from strict-clean modules is acceptable
because the call site is already typed.

**Status:** kept as `False`. Strict-clean modules must still annotate their
own definitions; this allowance only covers calls outward.

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

`mypy.ini` sets `ignore_missing_imports = True` for every third-party package
that ships no type information (SQLAlchemy, FastAPI, Pydantic, asyncpg,
python-jose, bcrypt, slowapi, httpx, Pillow, and the rest). This is the
**only** category of per-module override in the file.

Each entry is deliberate: the package genuinely has no stubs, and the import
boundary is typed by hand at the call site. This is not a suppression of
typing work; it is the standard mypy mechanism for untyped dependencies,
and it is listed explicitly so it is reviewable.

## Ratchet semantics

A module is "strict-clean" when `mypy --strict` reports zero errors for it
under this configuration. The ratchet baseline
(`tests/mypy_ratchet_baseline.json`) records which modules are strict-clean.
CI fails if a strict-clean module regresses. The set grows monotonically;
no module escapes the ratchet through new ignores or config exclusions.