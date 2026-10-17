# mypyc evaluation results and decision (issue #3258)

**Decision: no-go. Do not enable mypyc for any production module.**

This ticket was an evaluation, and a measured no-go is a complete result. The
candidates compile cleanly, behave equivalently, and do produce a real warm CPU
gain - but the gain is smaller than the cold-start cost it adds, and shipping
the artifacts would require new deployment machinery. The issue explicitly
rejects optimizations that "worsen serverless cold start or add deployment
complexity disproportionate to the gain", which is exactly what was measured.

The runnable harness, the reproduction recipe and the raw reports live beside
this file: [`README.md`](README.md), [`bench.py`](bench.py), and
[`results/`](results/).

## What was measured, and how

Six strict-clean, standard-library-only candidates from the Phase 0 shortlist:

`comic_pile.recommendation_weights`, `comic_pile.recommendation_weighting`,
`comic_pile.recommendation_selection`, `comic_pile.recommendation_version`,
`comic_pile.familiar_weighting`, `comic_pile.reading_effort`.

Two surfaces, same interpreter, same seeded inputs:

- `benchmark/mypyc/source/comic_pile/` - byte-identical copies of the production
  modules, executed as plain CPython.
- `benchmark/mypyc/compiled/comic_pile/` - the same copies plus the mypyc
  `__mypyc` + module `.so` pair, which shadows the `.py` at import time.

`bench.py` verifies the surface actually served each import (`.py` vs `.so`)
before it reports any equivalence result, so a mis-pointed comparison cannot
silently compare CPython against CPython.

### Environment

| Item | Value |
| --- | --- |
| Interpreter | CPython 3.14.8 (`cpython`) |
| mypy / mypyc | 2.4.0 |
| setuptools | 84.0.0 |
| Platform | `Linux-6.17.0-1022-azure-x86_64-with-glibc2.39` |
| Machine | `x86_64` |
| C compiler | `cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0` |
| Optimization | `mypycify(opt_level="3", debug_level="0", strip_asserts=False, multi_file=False, separate=True)` |

### Sampling

- **Warm**: 7 independent batches of 500 workload calls per workload, after an
  unrecorded warmup batch. Each batch yields one per-call millisecond sample, so
  every report carries observed min/median/mean/max/stdev/spread rather than one
  timing restated N times.
- **Cold**: 7 fresh interpreter processes per workload, plus 7 for the
  representative request. Total process wall time is observed by the parent (so
  it includes interpreter start-up and the import), and the child reports how
  that splits into candidate-surface import versus roll work.
- **Seed**: `20261017`. Identical inputs on both surfaces by construction,
  because the warm harness and the cold child call the same builders.
- **Workload sizes**: pool sizes 20 and 60; 120 effort pairs; 120 candidate
  signals; 100 familiar candidates with 24 taste signals; 4000 reading-effort
  observations.

## Warm execution (median of 7 samples x 500 calls, ms per call)

| Workload | CPython | mypyc | Speedup | CPython spread | mypyc spread |
| --- | ---: | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 0.3795 | 0.3869 | 0.981x | 1.20% | 1.46% |
| `weight_pool` | 1.2415 | 1.0864 | 1.143x | 0.51% | 0.43% |
| `select_from_pool` | 0.0397 | 0.0312 | 1.272x | 1.45% | 4.26% |
| `recommendation_version` | 0.0001 | 0.0002 | 0.500x | 33.12% | 2.14% |
| `compute_familiar_factors` | 2.5242 | 1.8827 | 1.341x | 2.65% | 0.37% |
| `aggregate_efforts` | 4.7727 | 4.1372 | 1.154x | 0.54% | 2.16% |

The gains are real but narrow. Only two candidates improve meaningfully
(`compute_familiar_factors` 1.34x, `select_from_pool` 1.27x). One is flat
(`build_candidate_weights` measured 0.981x, i.e. marginally *slower*; that
workload is dominated by interpreter overhead in the dataclass constructor
calls, which mypyc does not remove). `recommendation_version` is a constant read
with no CPU content; its CPython spread of 33.12% against a 0.0001 ms median is
the harness telling us the number is far below its own noise floor, so the
0.500x "speedup" is meaningless in both directions and should be read as "no
measurable difference".

Representative request initialization (import the whole candidate surface, then
run one roll-shaped call of every workload, measured in a fresh process):

| Quantity | CPython | mypyc | Delta |
| --- | ---: | ---: | ---: |
| Candidate-surface import | 9.5014 ms | 10.5847 ms | **+1.0833 ms** |
| In-process roll work | 9.9042 ms | 8.4059 ms | **-1.4983 ms** |
| Full process wall time | 86.6112 ms | 86.8298 ms | **+0.2186 ms** |

So the candidate surface gets ~15.1% cheaper to execute warm, and a cold
instance ends up ~0.22 ms slower end to end.

## Cold start (fresh process wall time, median of 7, ms)

| Workload | CPython | mypyc | Delta | Import delta |
| --- | ---: | ---: | ---: | ---: |
| `build_candidate_weights` | 71.8177 | 72.9726 | +1.1549 | +1.0447 |
| `weight_pool` | 72.5056 | 73.9652 | +1.4596 | +1.0663 |
| `select_from_pool` | 67.7927 | 69.0672 | +1.2745 | +1.0910 |
| `recommendation_version` | 68.0912 | 69.8156 | +1.7244 | +1.1865 |
| `compute_familiar_factors` | 71.8226 | 72.6381 | +0.8155 | +1.1338 |
| `aggregate_efforts` | 74.1101 | 75.2827 | +1.1726 | +1.1070 |
| `request_initialization` | 86.6112 | 86.8298 | +0.2186 | +1.0833 |

The import delta is the decisive column: **every row is positive, spanning
+1.04 ms to +1.19 ms.** Loading six shared objects through the dynamic loader
costs about a millisecond more than compiling six `.py` files. That per-process
penalty is structural, not a tuning artifact, and it is charged to every fresh
instance.

The total-delta column is positive in every row too, from +0.22 ms to
+1.72 ms. Its magnitude varies with how much CPU each single cold call does -
`request_initialization` runs all six workloads once, which claws most of the
import penalty back - but it never goes negative, and it never approaches
breaking even with the warm saving it is trying to amortize.

## Output equivalence

Verified on identical seeded inputs, comparing canonical JSON produced by a
fresh process pinned to each surface:

- Baseline served pure-Python modules for all six candidates: **true**.
- Candidate surface served native extensions for all six: **true**.
- **Numerically identical: true.** No value differences at any path.
- **Byte-identical including representation: false.** 52 representation-only
  differences, all of the same shape:

  ```text
  $.compute_familiar_factors.<id>.bonus: 0 (int) != 0.0 (float)
  ```

  These are the familiar-factor candidates with no matching Taste Bank signal.
  `comic_pile/familiar_weighting.py:424` computes
  `raw_bonus = sum(match.contribution for match in ordered_matches)`, so an
  empty match set yields the **int** `0` under CPython. mypyc infers `float`
  for that local, so it yields `0.0`. `min(0, MAX_FAMILIAR_BONUS)` and
  `min(0.0, MAX_FAMILIAR_BONUS)` then propagate the difference into
  `FamiliarFactor.bonus`.

  The values compare equal (`0 == 0.0`), and `FamiliarFactor.multiplier` is
  unaffected because it is `round(NEUTRAL_MULTIPLIER + bonus, 6)`. The practical
  effect is that a compiled build would serialize a no-match familiar bonus as
  `0.0` where the pure-Python build emits `0`. That is a wire-format difference
  in any response or log that projects `bonus`, which is a real reason to treat
  a rollout as a behavioural change rather than a transparent swap. It does not
  currently reach an API response - `app/` consumes familiar weighting only
  through the selection multiplier, not the `bonus` field.

### Existing regression coverage on the compiled surface

The dependency-free unit tests that exercise these modules were run against both
surfaces with the surface first on `PYTHONPATH`:

| Surface | Result |
| --- | --- |
| `source` (CPython) | 83 passed |
| `compiled` (mypyc) | 83 passed |

Files: `tests/test_familiar_weighting.py`, `tests/test_reading_effort.py`,
`tests/test_recommendation_weighting.py`. These import nothing but `pytest` and
the standard library, so they run without the application dependency tree. The
rest of `tests/` needs FastAPI, SQLAlchemy and PostgreSQL and was left to CI.

### Strict-clean gate

`mypy --strict --no-error-summary --show-error-codes` over the six candidates
(the canonical Phase 0 invocation from `scripts/generate_mypy_inventory.py`)
reports **0 errors inside the six candidate modules**. Errors reported elsewhere
come from modules the candidate import chain drags in (`comic_pile/queue.py`,
`comic_pile/reading_session.py`, `app/services/reading_eligibility_service.py`)
and are pre-existing Phase 1 backlog, not a candidate regression.

Repository gates for the whole tree, run locally after these changes:

| Command | Result |
| --- | --- |
| `ruff check .` | All checks passed |
| `ty check --error-on-warning` | All checks passed |

## Packaging and deployment

### Native artifacts

| Item | Value |
| --- | --- |
| Files produced | 12 `.so` (a module shim plus a `__mypyc` library per candidate) |
| Total `.so` size | 1,408,032 bytes |
| Pure-Python size shadowed | 75,843 bytes |
| Growth | ~18.6x for these modules |
| ELF | `ELF64`, machine `x86-64` |
| ABI tag | `cpython-314-x86_64-linux-gnu` |
| Dynamic deps | `libc.so.6` only - **no `libpython` link** |
| Max glibc symbol required | `GLIBC_2.14` |

Two of these are good news for a future rollout: the artifacts do not link
`libpython`, and the highest glibc symbol they need is `GLIBC_2.14`, so they
would load on Amazon Linux 2 (glibc 2.26) and AL2023 (glibc 2.34) as well as on
this Debian-based builder. The architecture matches both current targets
(x86-64).

### Clean installation

- **Clean-room import**: in a fresh 3.14 virtualenv with no `mypy` installed,
  copying only `compiled/comic_pile/` onto `PYTHONPATH` imports all six
  candidates successfully and returns correct results. The compiled modules need
  only the interpreter, as expected for a native build.
- **Wheel build**: `pip wheel --no-deps --no-build-isolation` produces
  `comic_pile_mypyc_bench-1.0.0-cp314-cp314-linux_x86_64.whl`, 502,847 bytes,
  `Root-Is-Purelib: false`. The wheel payload is the 12 `.so` files and no
  `.py`.
- **Wheel tag caveat**: the tag is `cp314-cp314-linux_x86_64`, a bare Linux
  platform tag, **not** a `manylinux` tag. It installs on a matching Linux
  x86_64 CPython 3.14 and is rejected elsewhere, but it carries no glibc floor
  metadata. Building a proper `manylinux` wheel (via `auditwheel`) would be an
  extra step in any future rollout.

### Docker

`Dockerfile` currently has no compile step and copies plain sources:
`COPY comic_pile/ ./comic_pile/` (line 84). A rollout would add a compile step
to the `python-builder` stage, which already installs `gcc` (lines 15-18), and
copy the resulting `.so` alongside the sources. Because the builder and runtime
stages share the `python:3.14-slim` base, the ABI and glibc match and this is
mechanically straightforward. The cost is `mypy` in the build image, +1.4 MB of
artifacts in the runtime image, and 76 KB of shadowed `.py` that would ship
alongside unless the copies are removed. None of that is prohibitive on its own;
the cost-benefit verdict is below.

### Vercel

`vercel.json` deploys `api/index.py` with `"use": "@vercel/python"`, and
`.python-version` pins `3.14`. Against Vercel's official Python runtime
documentation:

- **Version is supported.** Vercel lists 3.12 (default), 3.13 and 3.14, so the
  `cpython-314` ABI tag this build produces matches an available runtime.
  Source: <https://vercel.com/docs/functions/runtimes/python/python-version>
- **Bundling has no tree-shaking for Python.** "Python Vercel Functions include
  all files from your project that are reachable at build time. There is no
  automatic tree-shaking for Python." Vercel additionally compiles `.py` to
  bytecode automatically. Source:
  <https://vercel.com/docs/functions/runtimes/python>
- **No documented hook to compile project-local C extensions.** The documented
  control surface for what enters a Python function bundle is the `functions`
  property's `excludeFiles`, which only removes files. The `@vercel/python`
  builder takes dependencies from `pyproject.toml`/`requirements.txt`; there is
  no documented build command for compiling modules out of the project tree.
  `vercel.json` here passes no `config` to the builder, and
  `.github/workflows/deploy-production.yml` runs `vercel deploy` straight from a
  plain checkout.
- **`.so` files cannot simply be committed.** `.gitignore` lines 7 and 11 ignore
  `*.so` and `build/`, so build output is not committable in the first place.
- **Bundle limit is not the constraint.** The documented limit is 500 MB
  uncompressed, against a +1.4 MB change.

So Vercel packaging would require new machinery: either a custom build step
between checkout and `vercel deploy` that runs mypyc and arranges for the
artifacts to be included, or a committed platform-specific artifact set that the
current `.gitignore` and the "no tree-shaking" bundling behavior both work
against.

## Cost / benefit summary

| | Value |
| --- | --- |
| Warm CPU saved per full candidate pass | ~1.50 ms (9.90 ms -> 8.41 ms, -15.1%) |
| Largest single warm saving | `compute_familiar_factors`, ~0.64 ms, and it is one bounded-pool pass |
| Per-cold-instance cost | ~+1.08 ms of surface import; +0.22 ms to +1.72 ms measured end to end, never negative |
| Artifact size | +1.4 MB of `.so`, 18.6x the shadowed Python |
| Behavioural drift found | 52 `bonus: 0` vs `0.0` serialization differences |
| Deployment work required | Docker: a compile stage. Vercel: new build machinery that does not currently exist. |

Against a warm, long-lived container pool (the Docker deployment runs
`uvicorn --workers 2` behind a persistent service) the ~1.50 ms warm saving is
real but small relative to the request path, and it would be earned on every
request rather than once per cold start. Against the serverless deployment
(`api/index.py` under `@vercel/python`) the trade is strictly worse: every cold
instance pays ~+1.08 ms of extra loader work to save ~1.50 ms of CPU spread
across the entire lifetime of an instance that may serve a handful of requests.

The issue's acceptance criteria resolve this directly: *"Reject optimizations
that worsen serverless cold start or add deployment complexity disproportionate
to the gain."* Both conditions hold.

## Decision and follow-ups

**No-go.** No production module is compiled, no runtime switch is introduced, no
Dockerfile, `vercel.json` or workflow is modified, and no gate is weakened by
this change.

The artifact stays as a runnable, reproducible benchmark plus these recorded
results. If the recommendation path later becomes a measured production CPU
bottleneck - as opposed to the synthetic upper-pool workloads Phase 0 measured -
the revisit criteria are:

1. A profiling result showing these modules dominate real request CPU, not just
   synthetic pools.
2. A cold-start mitigation: either a deployment that does not pay per-instance
   loader cost, or measurement showing the compiled import cost is inside
   process-start noise for that deployment.
3. A decision on the `bonus: 0` vs `0.0` representation drift before any
   compiled artifact can be considered wire-compatible.

Any of those would be a separate bounded issue with its own rollout plan. This
ticket does not open one, because the current measurement says the work would
not pay for itself.