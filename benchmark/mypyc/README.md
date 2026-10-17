# mypyc evaluation harness (issue #3258)

Evaluation-only harness for the mypyc candidate modules. It produces the
measured evidence recorded in [`RESULTS.md`](RESULTS.md) and the go/no-go
decision for that issue. **Nothing in this directory is part of the production
runtime.** No application, script, test, migration or CI tooling file imports
anything from here, and no Docker or Vercel build path compiles these modules.

## Layout

| Path | Purpose |
| --- | --- |
| `source/comic_pile/` | CPython 3.14 baseline surface. Byte-identical copies of the production modules. |
| `compiled/comic_pile/` | The same copies plus the mypyc `__mypyc`/module `.so` pair after a build. The `.so` shadows the `.py` at import time. |
| `bench.py` | Warm timing, fresh-process cold timing, representative request initialization, output equivalence, artifact inventory, and report comparison. |
| `setup.py` | The `mypycify` build for the six candidate modules. |
| `mypy.ini` | mypy configuration scoped to this build only. See below. |
| `results/` | The measured reports committed with this evaluation, plus the rendered comparison. |

The copies exist so the two surfaces can differ at import time without touching
`comic_pile/` itself. `tests/test_mypyc_benchmark_artifact.py` fails if either
copy directory drifts from production, so the measurement always describes the
code that actually ships.

### Why `mypy.ini` exists here

`mypycify` discovers mypy configuration by walking up from the working
directory. Without a local config, running the build from `benchmark/mypyc/`
inherits the repository root `mypy.ini`, which sets `warn_unused_configs = True`
and declares per-module sections for the entire application's third-party
dependencies. A mypycify run references none of them, so mypy emits
`unused section(s): ...` through its error channel, mypycify sees a non-empty
error list, and the build aborts before compiling anything - with no message
beyond that note. `mypy.ini` here keeps the build independent of the repository
typing policy while keeping `strict = True`, so a real type error in a candidate
still fails the build.

## Candidates

`comic_pile.recommendation_weights`, `comic_pile.recommendation_weighting`,
`comic_pile.recommendation_selection`, `comic_pile.recommendation_version`,
`comic_pile.familiar_weighting`, `comic_pile.reading_effort`.

## Reproduction

Run from `benchmark/mypyc/` with a CPython 3.14 interpreter and a C compiler.
Both surfaces must be measured with the *same* interpreter; that is the whole
point of the comparison.

```bash
# 1. Compile the candidate surface. mypy ships the mypyc compiler.
python -m pip install mypy setuptools
python setup.py build_ext --inplace

# 2. Measure both surfaces. Inputs are seeded, so both surfaces see
#    byte-identical workloads.
python bench.py --root source   --output results/cpython.json
python bench.py --root compiled --output results/mypyc.json

# 3. Compare, verify output equivalence, render the decision table.
python bench.py --compare results/cpython.json results/mypyc.json \
    --output results/comparison.md
```

`--compare` exits non-zero when the two surfaces are not numerically
equivalent, or when a "comparison" is handed the same surface twice. It exits 0
when outputs are value-equal; representation-only differences are reported but
do not fail the run, because that is a recorded finding rather than a
correctness break.

Sampling defaults: `--warm-samples 7` independent batches of
`--warm-iterations 500` workload calls, and `--cold-samples 7` fresh
interpreter processes per workload. Every report records sample count, min,
median, mean, max, standard deviation and max-to-min spread, so a single lucky
timing cannot masquerade as a result.

### Running the existing regression tests against the compiled surface

`bench.py` does not run the repository test suite; it needs only the standard
library so it can be pointed at either surface. To prove the compiled modules
still satisfy the shipped unit tests, run the dependency-free test modules with
the surface first on `PYTHONPATH`:

```bash
# Resolve the repository root first; the pytest working directory has to be
# somewhere that does not contain a shadowing comic_pile package.
REPO_ROOT="$(cd ../../.. && pwd)"
REGRESSION=/tmp/mypyc-regression
mkdir -p "$REGRESSION"
cp "$REPO_ROOT/tests/test_familiar_weighting.py" \
   "$REPO_ROOT/tests/test_reading_effort.py" \
   "$REPO_ROOT/tests/test_recommendation_weighting.py" "$REGRESSION/"

for surface in source compiled; do
  (cd "$REGRESSION" && \
   PYTHONPATH="$REPO_ROOT/benchmark/mypyc/$surface" \
   python -m pytest -q test_familiar_weighting.py test_reading_effort.py \
     test_recommendation_weighting.py)
done
```

Those three modules import nothing but `pytest` and the standard library, so
they run without the application dependency tree. The rest of `tests/` needs
FastAPI, SQLAlchemy and a PostgreSQL instance and belongs in CI.

## What the harness deliberately does not do

- It does not modify `comic_pile/`, `app/`, the Dockerfile, `vercel.json`, or
  any workflow. This ticket is an evaluation, and the issue forbids a
  production runtime switch.
- It does not compile every file in `comic_pile/` or `app/`. Only the six
  measured candidates are compiled, and only in this throwaway benchmark tree.
- It does not weaken a gate, skip a test, or add a lint suppression.