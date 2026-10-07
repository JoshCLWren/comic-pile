# Strict mypy migration

Phase 0 (#3250, parent #3075) installs mypy 2.4.0 in the locked dev toolchain.
It targets Python 3.14 with `strict = true` in `pyproject.toml`. Existing ruff,
ty and pyright settings and enforcement are preserved. Production dependencies
and runtime behavior do not change.

Run from the repository root:

```bash
uv sync --locked
make mypy-check       # identical command in the CI python-mypy job
make mypy-inventory   # refresh docs/typing/mypy-inventory.json
uv run mypy          # complete strict target; expected to fail during migration
```

The intended surface is `app/`, `comic_pile/`, `api/`, `tests/`, and the baseline
runner itself. This covers production application code, the Vercel entry point,
and Python regression tests. `tests_e2e/` currently contains no Python sources.
Operator scripts, factory controllers, extraction utilities and Alembic migration
history are outside this first application migration surface. Imported local
modules outside the explicit surface are still analyzed and recorded.
`explicit_package_bases` gives namespace packages such as `scripts/` stable module
identities when tests import the runner.

## Strict-clean ratchet

`mypy-clean.json` lists exact Python paths that must remain strict-clean. It begins
with 16 already-clean domain modules plus the runner and its regression tests.
Adding paths expands enforcement; removing paths is a gate regression requiring
explicit review. Mypy analyzes the **entire** configured surface with normal import
following. The runner captures structured diagnostics and fails on errors attributed
to manifest files; other errors remain in the full inventory. This selection is a
bounded migration gate, not a declaration that the whole repository is clean.
No checker ignores, exclusions, import skipping or diagnostic-code suppression
are used. Checker crashes, invalid output and invalid manifests fail closed.

CI's `python-mypy` job runs the same locked runner command as `make mypy-check`; CI Summary explicitly requires it.
Mypy is supplied by the shared CI image's locked dev dependency installation.
Continue running `bash scripts/check-python-ci-lint.sh` and focused pytest coverage
before every Python push. Mypy supplements those gates.

To migrate a scope: inspect its inventory diagnostics, fix their underlying
contracts, add regression tests where behavior changes, add exact paths to the
manifest, refresh the inventory, and run all three Python checker gates. Never
remove an existing clean path to make a failed check pass.

## Intentional dynamic typing boundaries

Strict mypy is the target profile, not a universal prohibition of nested `Any`.
The repository's existing ruff ANN401 rule forbids bare `Any` function annotations;
its existing explicit per-file exceptions remain unchanged. Phase 0 introduces
no new exceptions. Existing dynamic JSON/report payloads legitimately contain
nested `Any` (for example ComicVine report classification and taste extraction,
exception log context, and legacy reconciliation reports). Preserve those honest
boundaries until actual validation supports a narrower contract. Mypy strict does
not enable `disallow_any_expr` or `disallow_any_explicit`; we intentionally do not
add them here. Strict's `no-any-return`, generic type arguments and typed-call
requirements still apply.

Prefer validated `object` with narrowing, concrete result types, TypedDicts for
known JSON shapes, or protocols for stable interfaces. Do not invent fake precise
shapes for arbitrary JSON, stack redundant casts, add unsafe casts, silence missing
third-party stubs globally, or replace an interface problem with `Any` merely to
reduce diagnostics. Missing external typing belongs in a bounded dependency or
adapter investigation.

## Inventory and migration queue

`mypy-inventory.json` includes every explicit file (including zero-error files),
imported-file evidence, module/package identity, exact counts per error code,
coherent family, conservative cleanup/interface triage, and raw file/line/message
evidence. Counts are a snapshot, not an allowed-error budget. Family classification
is code-based triage: interface review does not establish a runtime bug, and an
annotation family may still require understanding an interface. Refresh after the
last source edit; review actual diagnostics before changing a contract.

`migration-queue.md` summarizes the snapshot and links the next executable children.
Later children should cover one module or tightly coupled group, splitting large
groups by coherent error family. Do not generate one ticket per diagnostic.

## mypyc handoff

Strict-clean recommendation weighting/selection, familiar weighting and reading
effort modules are candidates for profiling, not proven optimization wins. The
separate evaluation ticket must first measure realistic CPU work and establish
which candidates are worthwhile. Compare identical CPython 3.14 and compiled
workloads, cold imports/startup in fresh processes, warm execution, artifact size,
and Vercel build/packaging compatibility. Reject gains outweighed by cold-start or
deployment costs. Phase 0 compiles and deploys no application code.

References: [mypy strict options](https://mypy.readthedocs.io/en/stable/command_line.html),
[import analysis](https://mypy.readthedocs.io/en/stable/running_mypy.html).
