#!/usr/bin/env python3
"""Warm-execution and cold-startup benchmark for the mypyc candidate modules.

Compares the CPython source copies (``benchmark/mypyc/source/comic_pile/``)
against the mypyc compiled extensions (``benchmark/mypyc/compiled/comic_pile/``)
for the five strict-clean modules named in issue #3258:

* ``comic_pile.recommendation_weights``
* ``comic_pile.recommendation_weighting``
* ``comic_pile.recommendation_selection``
* ``comic_pile.familiar_weighting``
* ``comic_pile.reading_effort``

Run once per interpreter surface and combine the two JSON reports:

    # CPython baseline (source only, no .so present)
    cd /tmp/opencode  # neutral cwd so the repo's real comic_pile package is not shadowed
    PYTHONPATH=$PWD/../comic-pile/benchmark/mypyc/source python \
        $PWD/../comic-pile/benchmark/mypyc/bench.py --root source --output cpython.json

    # mypyc compiled extensions (.so files shadow the .py files at import time)
    PYTHONPATH=$PWD/../comic-pile/benchmark/mypyc/compiled python \
        $PWD/../comic-pile/benchmark/mypyc/bench.py --root compiled --output mypyc.json

The cold-startup measurement launches a fresh Python process per sample so it
captures real interpreter import+initialization cost, not just warm call cost.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, TypeVar, cast
from collections.abc import Callable

# ---------------------------------------------------------------------------
# Candidate modules (strict-clean, stdlib-only) from issue #3258.
# They are imported dynamically after the benchmark root is on sys.path so the
# same bench.py runs unchanged against both CPython source and mypyc .so.
# ---------------------------------------------------------------------------

MODULES = (
    "comic_pile.recommendation_weights",
    "comic_pile.recommendation_weighting",
    "comic_pile.recommendation_selection",
    "comic_pile.familiar_weighting",
    "comic_pile.reading_effort",
)

# ---------------------------------------------------------------------------
# Workload sizes. Representative of a bounded die-pool roll plus a larger
# reading-effort aggregation, while staying fast enough to sample repeatedly.
# ---------------------------------------------------------------------------

POOL_SIZES = (20, 60)
EFFORT_COUNT = 120
SIGNAL_COUNT = 120
OBSERVATION_COUNT = 4000
FAMILIAR_CANDIDATE_COUNT = 100
FAMILIAR_SIGNAL_COUNT = 24

WARM_ITERATIONS = 3000
COLD_SAMPLES = 7


@dataclass(frozen=True)
class ModuleResult:
    """Aggregated warm + cold measurements for one module workload."""

    module: str
    workload: str
    interpreter: str
    warm_ms: dict[str, float | None]
    cold_ms: dict[str, float | None]


def _rng() -> random.Random:
    return random.Random(20261017)


def _build_efforts() -> list[tuple[int, float | None]]:
    rng = _rng()
    efforts: list[tuple[int, float | None]] = []
    for index in range(EFFORT_COUNT):
        band = index % 4
        if band == 0:
            effort = rng.uniform(1.0, 11.0)  # light
        elif band == 1:
            effort = rng.uniform(12.0, 17.0)  # medium
        elif band == 2:
            effort = rng.uniform(18.0, 40.0)  # heavy
        else:
            effort = None  # unknown
        efforts.append((1000 + index, effort))
    return efforts


def _build_signals(candidate_signals: Any) -> list[Any]:
    rng = _rng()
    signals: list[Any] = []
    for index in range(SIGNAL_COUNT):
        signals.append(
            cast(Any, candidate_signals)(
                thread_id=2000 + index,
                effort_minutes=rng.choice([None, 5.0, 14.0, 22.0]),
                last_rating=rng.choice([None, 3.0, 4.0, 5.0]),
                days_since_last_read=rng.choice([None, 2.0, 10.0, 30.0, 60.0]),
                high_rated_streak=rng.randint(0, 5),
                matched_verdict_by_category=(
                    {"creator": "confirmed"} if index % 3 == 0 else {}
                ),
                prior_exposure_count=rng.randint(0, 5),
                adjacent_anchor_categories=(
                    ["publisher"] if index % 4 == 0 else []
                ),
            )
        )
    return signals


def _build_weights(pool_size: int) -> list[float]:
    return [1.0 + (i % 3) * 0.25 for i in range(pool_size)]


def _build_familiar_inputs(
    candidate_familiar_keys: object,
    creator_credit_key: object,
    taste_signal: object,
) -> tuple[dict[int, Any], list[Any]]:
    _rng()  # Initialize random seed but don't store the result
    candidates: dict[int, Any] = {}
    for index in range(FAMILIAR_CANDIDATE_COUNT):
        credits = (
            (
                creator_credit_key(key="stan lee", roles=frozenset({"writer"})),
                creator_credit_key(key="jack kirby", roles=frozenset({"artist"})),
            )
            if index % 2 == 0
            else ()
        )
        candidates[index] = candidate_familiar_keys(
            creator_roles=credits,
            characters=frozenset({"spider-man", "x-men"})
            if index % 3 == 0
            else frozenset(),
            teams=frozenset({"avengers"}) if index % 4 == 0 else frozenset(),
            publishers=frozenset({"marvel"}) if index % 5 == 0 else frozenset(),
            eras=frozenset({"1960s"}) if index % 6 == 0 else frozenset(),
        )
    signals = [
        taste_signal(kind="creator_role", key="stan lee", verdict="confirmed"),
        taste_signal(kind="character", key="spider-man", verdict="confirmed"),
        taste_signal(kind="team", key="avengers", verdict="sometimes"),
        taste_signal(kind="publisher", key="marvel", verdict="confirmed"),
        taste_signal(kind="era", key="1960s", verdict="confirmed"),
        taste_signal(kind="creator_role", key="jack kirby", verdict="rejected"),
    ] * (FAMILIAR_SIGNAL_COUNT // 6 + 1)
    return candidates, signals[:FAMILIAR_SIGNAL_COUNT]


def _build_observations(effort_observation: object) -> list[Any]:
    rng = _rng()
    observations: list[Any] = []
    for index in range(OBSERVATION_COUNT):
        observations.append(
            effort_observation(
                thread_id=3000 + (index % 50),
                issue_id=4000 + (index % 200),
                duration_seconds=rng.uniform(300.0, 2400.0),
            )
        )
    return observations


def _import_candidates(root: str) -> dict[str, Any]:
    """Insert ``root`` on sys.path and import all candidate modules."""
    sys.path.insert(0, root)
    try:
        imported: dict[str, Any] = {}
        for name in MODULES:
            imported[name] = importlib.import_module(name)
        return imported
    finally:
        sys.path.remove(root)


def _workloads(mods: dict[str, Any]) -> list[tuple[str, str, Callable[[Any], None]]]:
    """Return (module, label, callable) triples running one representative call each."""
    rec_weighting_mod = mods["comic_pile.recommendation_weighting"]
    rec_selection_mod = mods["comic_pile.recommendation_selection"]
    familiar_mod = mods["comic_pile.familiar_weighting"]
    effort_mod = mods["comic_pile.reading_effort"]

    efforts = _build_efforts()
    signals = _build_signals(rec_weighting_mod.CandidateSignals)
    candidates, familiar_signals = _build_familiar_inputs(
        familiar_mod.CandidateFamiliarKeys,
        familiar_mod.CreatorCreditKey,
        familiar_mod.TasteSignal,
    )
    observations = _build_observations(effort_mod.EffortObservation)
    rng = _rng()
    default_min_trusted_sample_count = effort_mod.DEFAULT_MIN_TRUSTED_SAMPLE_COUNT

    def rec_weights(mod) -> None:
        mod.build_candidate_weights(efforts, "light")
        mod.build_candidate_weights(efforts, "balanced")
        mod.build_candidate_weights(efforts, "deep")

    def rec_weighting(mod) -> None:
        mod.weight_pool("light", "momentum", signals)
        mod.weight_pool("balanced", "balanced", signals)
        mod.weight_pool("deep", "explore", signals)

    def rec_selection(mod) -> None:
        bandwidth = rec_selection_mod.Bandwidth
        intent = rec_selection_mod.Intent
        for pool_size in POOL_SIZES:
            weights = _build_weights(pool_size)
            mod.select_from_pool(pool_size, rng=rng)
            mod.select_from_pool(
                pool_size,
                bandwidth=bandwidth.LIGHT,
                intent=intent.MOMENTUM,
                weights=weights,
                rng=rng,
            )
            mod.select_from_pool(pool_size, intent=intent.RANDOM, rng=rng)

    def familiar(mod) -> None:
        mod.compute_familiar_factors(candidates, familiar_signals)

    def effort(mod) -> None:
        mod.aggregate_efforts(
            observations, min_trusted_sample_count=default_min_trusted_sample_count
        )

    return [
        (
            "comic_pile.recommendation_weights",
            "build_candidate_weights",
            rec_weights,
        ),
        (
            "comic_pile.recommendation_weighting",
            "weight_pool",
            rec_weighting,
        ),
        (
            "comic_pile.recommendation_selection",
            "select_from_pool",
            rec_selection,
        ),
        ("comic_pile.familiar_weighting", "compute_familiar_factors", familiar),
        ("comic_pile.reading_effort", "aggregate_efforts", effort),
    ]


def _warm_benchmark(
    root: str, module: str, label: str, fn: Callable[[Any], None], iterations: int
) -> list[float]:
    """Run ``fn`` ``iterations`` times against the importable module (per-call ms)."""
    imported = _import_candidates(root)
    mod = imported[module]

    # One unrecorded warmup so first-call attribute overhead is settled.
    fn(mod)

    started = time.perf_counter()
    for _ in range(iterations):
        fn(mod)
    elapsed = time.perf_counter() - started
    per_call = (elapsed * 1000.0) / iterations
    return [per_call] * iterations


def _workload_source(module: str) -> str:
    """Return subprocess source that rebuilds the workload data and calls one module."""
    header = (
        "import random, time\n"
        "rng = random.Random(20261017)\n"
        f"import sys\n"
        f"sys.path.insert(0, {os.path.abspath(__import__('os').path.dirname(__import__('os').path.abspath(__file__)) + '/..')!r})\n"
    )
    # Note: the caller prepends the actual root via _cold_benchmark; this header
    # keeps sys.path manipulation minimal. The real root is injected below.
    header = (
        "import random, sys, time\n"
        "rng = random.Random(20261017)\n"
    )
    if module == "comic_pile.recommendation_weights":
        body = (
            "import comic_pile.recommendation_weights\n"
            "started = time.perf_counter()\n"
            "efforts = [(i, rng.choice([None, 5.0, 14.0, 22.0])) for i in range(120)]\n"
            "comic_pile.recommendation_weights.build_candidate_weights(efforts, 'light')\n"
            "comic_pile.recommendation_weights.build_candidate_weights(efforts, 'balanced')\n"
            "comic_pile.recommendation_weights.build_candidate_weights(efforts, 'deep')\n"
            "print(f'{time.perf_counter() - started:.6f}')\n"
        )
    elif module == "comic_pile.recommendation_weighting":
        body = (
            "import comic_pile.recommendation_weighting\n"
            "from comic_pile.recommendation_weighting import CandidateSignals\n"
            "started = time.perf_counter()\n"
            "signals = [\n"
            "    CandidateSignals(\n"
            "        thread_id=2000+i,\n"
            "        effort_minutes=rng.choice([None, 5.0, 14.0, 22.0]),\n"
            "        last_rating=rng.choice([None, 3.0, 4.0, 5.0]),\n"
            "        days_since_last_read=rng.choice([None, 2.0, 10.0, 30.0, 60.0]),\n"
            "        high_rated_streak=rng.randint(0, 5),\n"
            "        matched_verdict_by_category={'creator': 'confirmed'} if i % 3 == 0 else {},\n"
            "        prior_exposure_count=rng.randint(0, 5),\n"
            "        adjacent_anchor_categories=['publisher'] if i % 4 == 0 else [],\n"
            "    )\n"
            "    for i in range(120)\n"
            "]\n"
            "comic_pile.recommendation_weighting.weight_pool('light', 'momentum', signals)\n"
            "comic_pile.recommendation_weighting.weight_pool('balanced', 'balanced', signals)\n"
            "comic_pile.recommendation_weighting.weight_pool('deep', 'explore', signals)\n"
            "print(f'{time.perf_counter() - started:.6f}')\n"
        )
    elif module == "comic_pile.recommendation_selection":
        body = (
            "import comic_pile.recommendation_selection\n"
            "from comic_pile.recommendation_selection import Bandwidth, Intent\n"
            "started = time.perf_counter()\n"
            "for pool_size in (20, 60):\n"
            "    weights = [1.0 + (i % 3) * 0.25 for i in range(pool_size)]\n"
            "    comic_pile.recommendation_selection.select_from_pool(pool_size, rng=rng)\n"
            "    comic_pile.recommendation_selection.select_from_pool(\n"
            "        pool_size,\n"
            "        bandwidth=Bandwidth.LIGHT,\n"
            "        intent=Intent.MOMENTUM,\n"
            "        weights=weights,\n"
            "        rng=rng,\n"
            "    )\n"
            "    comic_pile.recommendation_selection.select_from_pool(\n"
            "        pool_size, intent=Intent.RANDOM, rng=rng\n"
            "    )\n"
            "print(f'{time.perf_counter() - started:.6f}')\n"
        )
    elif module == "comic_pile.familiar_weighting":
        body = (
            "import comic_pile.familiar_weighting\n"
            "from comic_pile.familiar_weighting import (\n"
            "    CandidateFamiliarKeys,\n"
            "    CreatorCreditKey,\n"
            "    TasteSignal,\n"
            ")\n"
            "started = time.perf_counter()\n"
            "candidates = {}\n"
            "for index in range(100):\n"
            "    credits = (\n"
            "        CreatorCreditKey(key='stan lee', roles=frozenset({'writer'})),\n"
            "        CreatorCreditKey(key='jack kirby', roles=frozenset({'artist'})),\n"
            "    ) if index % 2 == 0 else ()\n"
            "    candidates[index] = CandidateFamiliarKeys(\n"
            "        creator_roles=credits,\n"
            "        characters=frozenset({'spider-man', 'x-men'}) if index % 3 == 0 else frozenset(),\n"
            "        teams=frozenset({'avengers'}) if index % 4 == 0 else frozenset(),\n"
            "        publishers=frozenset({'marvel'}) if index % 5 == 0 else frozenset(),\n"
            "        eras=frozenset({'1960s'}) if index % 6 == 0 else frozenset(),\n"
            "    )\n"
            "signals = [\n"
            "    TasteSignal(kind='creator_role', key='stan lee', verdict='confirmed'),\n"
            "    TasteSignal(kind='character', key='spider-man', verdict='confirmed'),\n"
            "    TasteSignal(kind='team', key='avengers', verdict='sometimes'),\n"
            "    TasteSignal(kind='publisher', key='marvel', verdict='confirmed'),\n"
            "    TasteSignal(kind='era', key='1960s', verdict='confirmed'),\n"
            "    TasteSignal(kind='creator_role', key='jack kirby', verdict='rejected'),\n"
            "] * 5\n"
            "comic_pile.familiar_weighting.compute_familiar_factors(candidates, signals[:24])\n"
            "print(f'{time.perf_counter() - started:.6f}')\n"
        )
    elif module == "comic_pile.reading_effort":
        body = (
            "import comic_pile.reading_effort\n"
            "from comic_pile.reading_effort import EffortObservation, DEFAULT_MIN_TRUSTED_SAMPLE_COUNT\n"
            "started = time.perf_counter()\n"
            "observations = [\n"
            "    EffortObservation(thread_id=3000 + (i % 50), issue_id=4000 + (i % 200), duration_seconds=rng.uniform(300.0, 2400.0))\n"
            "    for i in range(4000)\n"
            "]\n"
            "comic_pile.reading_effort.aggregate_efforts(\n"
            "    observations,\n"
            "    min_trusted_sample_count=DEFAULT_MIN_TRUSTED_SAMPLE_COUNT,\n"
            ")\n"
            "print(f'{time.perf_counter() - started:.6f}')\n"
        )
    else:
        raise ValueError(f"unknown module: {module}")
    return header + body


def _cold_benchmark(root: str, module: str, label: str, samples: int) -> list[float]:
    """Launch fresh Python processes to import + run the workload once each (ms)."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, {root!r})\n"
        + _workload_source(module)
    )

    # One unrecorded warmup process so site-packages are loaded.
    subprocess.run([sys.executable, "-c", script], capture_output=True, check=True)

    elapsed_seconds: list[float] = []
    for _ in range(samples):
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            text=True,
        )
        elapsed_seconds.append(float(result.stdout.strip()))
    return [s * 1000.0 for s in elapsed_seconds]


def _aggregate(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "count": 0,
            "min_ms": None,
            "median_ms": None,
            "max_ms": None,
            "mean_ms": None,
        }
    return {
        "count": len(values),
        "min_ms": round(min(values), 4),
        "median_ms": round(statistics.median(values), 4),
        "max_ms": round(max(values), 4),
        "mean_ms": round(statistics.fmean(values), 4),
    }


def main() -> int:
    """Run the benchmark and print JSON results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        required=True,
        help="Import root: 'source' (CPython .py) or 'compiled' (mypyc .so) directory under benchmark/mypyc/",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=WARM_ITERATIONS,
        help="Warm-execution iterations per workload.",
    )
    parser.add_argument(
        "--cold-samples",
        type=int,
        default=COLD_SAMPLES,
        help="Cold fresh-process samples per workload.",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the JSON report.",
    )
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root_map = {
        "source": os.path.join(here, "source"),
        "compiled": os.path.join(here, "compiled"),
    }
    if args.root not in root_map:
        parser.error(f"--root must be one of {sorted(root_map)}")
    root = root_map[args.root]

    interpreter = "mypyc" if args.root == "compiled" else "cpython"

    mods = _import_candidates(root)
    workloads = _workloads(mods)

    results: list[dict[str, Any]] = []
    for module, label, fn in workloads:
        warm = _warm_benchmark(root, module, label, fn, args.iterations)
        cold = _cold_benchmark(root, module, label, args.cold_samples)
        results.append(
            asdict(
                ModuleResult(
                    module=module,
                    workload=label,
                    interpreter=interpreter,
                    warm_ms=_aggregate(warm),
                    cold_ms=_aggregate(cold),
                )
            )
        )

    report: dict[str, Any] = {
        "benchmark": "mypyc-cpu-evaluation",
        "issue": 3258,
        "interpreter": interpreter,
        "python_implementation": sys.implementation.name,
        "python_version": sys.version,
        "root": root,
        "warm_iterations": args.iterations,
        "cold_samples": args.cold_samples,
        "results": results,
    }

    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
