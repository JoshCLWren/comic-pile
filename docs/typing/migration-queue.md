# Phase 0 inventory and executable migration queue

Snapshot produced by `make mypy-inventory` with mypy 2.4.0 (compiled: yes).

692 explicit Python files; 1799 strict errors.
The strict-clean manifest enforces 18 files. Counts below include imported local
modules; this is not a repo-wide clean claim.

| Package | Strict errors |
| --- | ---: |
| `app` | 384 |
| `comic_pile` | 22 |
| `scripts` | 79 |
| `tests` | 1314 |

| Error code | Count |
| --- | ---: |
| `no-untyped-def` | 733 |
| `arg-type` | 349 |
| `type-arg` | 176 |
| `call-overload` | 108 |
| `no-untyped-call` | 79 |
| `assignment` | 74 |
| `attr-defined` | 72 |
| `index` | 42 |
| `no-any-return` | 34 |
| `typeddict-item` | 19 |
| `comparison-overlap` | 19 |
| `var-annotated` | 15 |
| `list-item` | 13 |
| `method-assign` | 13 |
| `call-arg` | 12 |
| `misc` | 9 |
| `func-returns-value` | 6 |
| `import-untyped` | 5 |
| `operator` | 4 |
| `type-var` | 4 |
| `union-attr` | 3 |
| `dict-item` | 3 |
| `unused-ignore` | 3 |
| `return-value` | 2 |
| `name-defined` | 1 |
| `valid-type` | 1 |

Full module/package, code/family, cleanup/interface triage and raw diagnostics are
in [mypy-inventory.json](mypy-inventory.json). Annotation completeness dominates
the test surface; application contract and dynamic-boundary findings need
interface inspection. No existing diagnostic is suppressed in the target config.

## Next bounded children

These depend on #3250 and are executable after the Phase 0 gate merges. They are
initial slices of the inventory, not the entire migration. Remaining scopes will
be ticketed in bounded groups as this queue advances.

- [Strict mypy Phase 1: clean bandwidth domain contracts](https://github.com/JoshCLWren/comic-pile/issues/3253): `comic_pile/bandwidth.py`, `comic_pile/bandwidth_correction.py`; 3 baseline errors.
- [Strict mypy Phase 1: clean queue and dependency domain contracts](https://github.com/JoshCLWren/comic-pile/issues/3254): `comic_pile/queue.py`, `comic_pile/dependencies.py`; 9 baseline errors.
- [Strict mypy Phase 1: narrow explore scoring result](https://github.com/JoshCLWren/comic-pile/issues/3255): `comic_pile/explore_scoring.py`; 1 baseline errors.
- [Strict mypy Phase 1: type ComicVine provider adapter](https://github.com/JoshCLWren/comic-pile/issues/3256): `comic_pile/comicvine_provider.py`; 4 baseline errors.
- [Strict mypy Phase 1: annotate factory workflow contract tests](https://github.com/JoshCLWren/comic-pile/issues/3257): `tests/test_factory_runtime_evidence_workflow.py`, `tests/test_factory_dispatch_workflow.py`; 16 baseline errors.

[Separate mypyc evaluation #3258](https://github.com/JoshCLWren/comic-pile/issues/3258) profiles the strict-clean
pure modules before deciding what to compile. It requires CPython 3.14 parity,
cold-import/startup and warm benchmarks, and Vercel packaging evidence. Production
compilation requires a subsequent rollout issue and is outside Phase 0.
