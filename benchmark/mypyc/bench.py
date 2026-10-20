#!/usr/bin/env python3
"""Warm-execution and cold-start benchmark for the mypyc candidate modules.

Compares the CPython source surface (``benchmark/mypyc/source/comic_pile/``)
against the mypyc compiled surface (``benchmark/mypyc/compiled/comic_pile/``)
for the strict-clean modules named in issue #3258:

* ``comic_pile.recommendation_weights``
* ``comic_pile.recommendation_weighting``
* ``comic_pile.recommendation_selection``
* ``comic_pile.recommendation_version``
* ``comic_pile.familiar_weighting``
* ``comic_pile.reading_effort``

Two measurement kinds are recorded per workload, and they are deliberately kept
apart because they answer different questions:

* **warm** - repeated execution of an already-imported module. The parent
  process imports the surface once, then times ``--warm-samples`` independent
  batches of ``--warm-iterations`` workload calls each. Each batch yields one
  per-call millisecond sample, so the report carries real observed variability
  instead of a single number restated N times.
* **cold** - a fresh interpreter process per sample. The parent observes total
  process wall time, which includes interpreter startup, site initialization,
  the candidate import and one workload call. The child additionally reports how
  that total splits into candidate-import time versus workload time, so a
  regression in import cost is distinguishable from a regression in call cost.

Every workload is deterministic. Inputs are generated from one fixed seed, and
the same generator functions feed both the warm harness and the cold child, so
the two surfaces always receive byte-identical inputs.

Reproducible commands (from the repository root):

    cd benchmark/mypyc
    python -m pip install mypy setuptools      # mypy ships the mypyc compiler
    python setup.py build_ext --inplace        # writes compiled/comic_pile/*.so

    # CPython 3.14 baseline (no .so present on this surface)
    python bench.py --root source --output results/cpython.json

    # mypyc compiled surface (.so shadows the .py at import time)
    python bench.py --root compiled --output results/mypyc.json

    # Merge both reports, verify output equivalence, emit the decision table
    python bench.py --compare results/cpython.json results/mypyc.json \
        --output results/comparison.md

Run both surfaces with the *same* interpreter: the whole point of the
comparison is one CPython 3.14 baseline versus the same interpreter with those
six modules replaced by native extensions.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from importlib import metadata
from types import ModuleType

# ---------------------------------------------------------------------------
# Candidate modules (strict-clean, stdlib-only) from issue #3411 (extended
# from #3258). They are imported dynamically after the benchmark root is placed
# first on sys.path so this one file runs unchanged against both the CPython and
# mypyc surfaces.
# ---------------------------------------------------------------------------

MODULES = (
    "comic_pile.recommendation_weights",
    "comic_pile.recommendation_weighting",
    "comic_pile.recommendation_selection",
    "comic_pile.recommendation_version",
    "comic_pile.familiar_weighting",
    "comic_pile.reading_effort",
    "comic_pile.snooze_backoff",
    "comic_pile.reading_effort_observation_rules",
    "comic_pile.comicvine_report_classification",
    "comic_pile.dice_ladder",
)

#: Seed shared by every generated input. Fixed so both surfaces are fed
#: identical inputs and so re-running the benchmark reproduces the same work.
SEED = 20261017

# ---------------------------------------------------------------------------
# Workload sizes. Sized to look like one bounded die-pool roll plus a larger
# reading-effort aggregation, while staying fast enough to sample repeatedly.
# ---------------------------------------------------------------------------

POOL_SIZES = (20, 60)
EFFORT_COUNT = 120
SIGNAL_COUNT = 120
OBSERVATION_COUNT = 4000
FAMILIAR_CANDIDATE_COUNT = 100
FAMILIAR_SIGNAL_COUNT = 24

#: Default independent warm batches per workload.
WARM_SAMPLES = 7
#: Default workload calls inside one warm batch.
WARM_ITERATIONS = 500
#: Default fresh processes per cold workload.
COLD_SAMPLES = 7

#: Pseudo-workload name for the fresh-process representative-request case.
REQUEST_INIT = "request_initialization"

#: Upper bound on how many individual equivalence differences the Markdown
#: report spells out, so a systematic representation change cannot swamp it.
_MAX_RENDERED_DIFFERENCES = 8


def _rng() -> random.Random:
    """Return a generator seeded from :data:`SEED`.

    Returns:
        Fresh :class:`random.Random` bound to the fixed benchmark seed.
    """
    return random.Random(SEED)


# ---------------------------------------------------------------------------
# Deterministic input builders. These are the single source of workload inputs;
# both the warm harness and the cold child call them, so the two measurement
# kinds cannot drift onto different data.
# ---------------------------------------------------------------------------


def build_effort_pairs() -> list[tuple[int, float | None]]:
    """Build the ``(thread_id, effort_minutes)`` pairs used for weight building.

    Returns:
        Deterministically generated effort pairs spanning light, medium, heavy
        and unknown bands.
    """
    rng = _rng()
    efforts: list[tuple[int, float | None]] = []
    for index in range(EFFORT_COUNT):
        band = index % 4
        if band == 0:
            effort: float | None = rng.uniform(1.0, 11.0)
        elif band == 1:
            effort = rng.uniform(12.0, 17.0)
        elif band == 2:
            effort = rng.uniform(18.0, 40.0)
        else:
            effort = None
        efforts.append((1000 + index, effort))
    return efforts


def build_signals(candidate_signals: Callable[..., object]) -> list[object]:
    """Build the bounded candidate-signal pool used for pool weighting.

    Args:
        candidate_signals: The ``CandidateSignals`` class from the surface under
            test.

    Returns:
        Deterministically generated signal objects.
    """
    rng = _rng()
    signals: list[object] = []
    for index in range(SIGNAL_COUNT):
        signals.append(
            candidate_signals(
                thread_id=2000 + index,
                effort_minutes=rng.choice([None, 5.0, 14.0, 22.0]),
                last_rating=rng.choice([None, 3.0, 4.0, 5.0]),
                days_since_last_read=rng.choice([None, 2.0, 10.0, 30.0, 60.0]),
                high_rated_streak=rng.randint(0, 5),
                matched_verdict_by_category={"creator": "confirmed"} if index % 3 == 0 else {},
                prior_exposure_count=rng.randint(0, 5),
                adjacent_anchor_categories=["publisher"] if index % 4 == 0 else [],
            )
        )
    return signals


def build_weights(pool_size: int) -> list[float]:
    """Build a deterministic weight vector for one pool size.

    Args:
        pool_size: Number of candidates in the simulated pool.

    Returns:
        Weight vector of length ``pool_size``.
    """
    return [1.0 + (i % 3) * 0.25 for i in range(pool_size)]


def build_familiar_inputs(
    candidate_familiar_keys: Callable[..., object],
    creator_credit_key: Callable[..., object],
    taste_signal: Callable[..., object],
) -> tuple[dict[int, object], list[object]]:
    """Build the candidate keys and Taste Bank signals for familiar scoring.

    Args:
        candidate_familiar_keys: ``CandidateFamiliarKeys`` from the surface.
        creator_credit_key: ``CreatorCreditKey`` from the surface.
        taste_signal: ``TasteSignal`` from the surface.

    Returns:
        Tuple of candidate-id to familiar-keys mapping and the signal list.
    """
    candidates: dict[int, object] = {}
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
            characters=frozenset({"spider man", "x men"}) if index % 3 == 0 else frozenset(),
            teams=frozenset({"avengers"}) if index % 4 == 0 else frozenset(),
            publishers=frozenset({"marvel"}) if index % 5 == 0 else frozenset(),
            eras=frozenset({"1960s"}) if index % 6 == 0 else frozenset(),
        )
    signals = [
        taste_signal(kind="creator_role", key="stan lee", verdict="confirmed"),
        taste_signal(kind="character", key="spider man", verdict="confirmed"),
        taste_signal(kind="team", key="avengers", verdict="sometimes"),
        taste_signal(kind="publisher", key="marvel", verdict="confirmed"),
        taste_signal(kind="era", key="1960s", verdict="confirmed"),
        taste_signal(kind="creator_role", key="jack kirby", verdict="rejected"),
    ] * (FAMILIAR_SIGNAL_COUNT // 6 + 1)
    return candidates, signals[:FAMILIAR_SIGNAL_COUNT]


def build_observations(effort_observation: Callable[..., object]) -> list[object]:
    """Build the reading-effort observation set for aggregation.

    Args:
        effort_observation: ``EffortObservation`` from the surface.

    Returns:
        Deterministically generated reading-effort observations.
    """
    rng = _rng()
    observations: list[object] = []
    for index in range(OBSERVATION_COUNT):
        observations.append(
            effort_observation(
                thread_id=3000 + (index % 50),
                issue_id=4000 + (index % 200),
                duration_seconds=rng.uniform(300.0, 2400.0),
            )
        )
    return observations


# ---------------------------------------------------------------------------
# Import surface handling
# ---------------------------------------------------------------------------


def surface_name(root: str) -> str:
    """Classify an import root as the ``cpython`` or ``mypyc`` surface.

    Args:
        root: Filesystem path placed first on ``sys.path``.

    Returns:
        ``"mypyc"`` when native extension modules are present under ``root``,
        otherwise ``"cpython"``.
    """
    package = os.path.join(root, "comic_pile")
    try:
        entries = os.listdir(package)
    except OSError:
        return "cpython"
    return "mypyc" if any(name.endswith(".so") for name in entries) else "cpython"


def import_candidates(root: str) -> dict[str, ModuleType]:
    """Import every candidate module from ``root`` with ``root`` taking priority.

    The package is imported from an already-imported ``sys.modules`` entry when
    one exists, so a surface switch cannot silently mix two copies of
    ``comic_pile`` inside a single process.

    Args:
        root: Directory that contains the ``comic_pile`` package to measure.

    Returns:
        Mapping of dotted module name to the imported module object.
    """
    if root not in sys.path:
        sys.path.insert(0, root)
    imported: dict[str, ModuleType] = {}
    for name in MODULES:
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", "") or ""
        expected = os.path.join(os.path.realpath(root), *name.split("."))
        if os.path.realpath(origin) and not os.path.realpath(origin).startswith(expected):
            msg = f"{name} resolved to {origin}, which is outside {root}"
            raise RuntimeError(msg)
        imported[name] = module
    return imported


# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Workload:
    """One benchmarkable unit of candidate-module CPU work."""

    name: str
    module: str
    call: Callable[[ModuleType, dict[str, ModuleType]], object]
    describe: str
    #: Whether this workload belongs in the request-shaped cold-start sample.
    #: Offline batch work (for example hydration-report classification) is still
    #: measured warm and cold, but it is not charged to a serverless request.
    request_shaped: bool = True


def _w_build_candidate_weights(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Build candidate weights for the three bandwidth modes."""
    efforts = build_effort_pairs()
    return {
        mode: mod.build_candidate_weights(efforts, mode)
        for mode in ("light", "balanced", "deep")
    }


def _w_weight_pool(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Weight the bounded candidate pool for three bandwidth/intent pairs."""
    signals = build_signals(_mods["comic_pile.recommendation_weighting"].CandidateSignals)
    return {
        f"{bandwidth}/{intent}": mod.weight_pool(bandwidth, intent, signals)
        for bandwidth, intent in (
            ("light", "momentum"),
            ("balanced", "balanced"),
            ("deep", "explore"),
        )
    }


def _w_select_from_pool(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Draw from two bounded pool sizes across three control paths."""
    selection_mod = _mods["comic_pile.recommendation_selection"]
    rng = _rng()
    draws: list[object] = []
    for pool_size in POOL_SIZES:
        weights = build_weights(pool_size)
        draws.append(mod.select_from_pool(pool_size, rng=rng))
        draws.append(
            mod.select_from_pool(
                pool_size,
                bandwidth=selection_mod.Bandwidth.LIGHT,
                intent=selection_mod.Intent.MOMENTUM,
                weights=weights,
                rng=rng,
            )
        )
        draws.append(
            mod.select_from_pool(
                pool_size, intent=selection_mod.Intent.RANDOM, rng=rng
            )
        )
    return draws


def _w_recommendation_version(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Read the current recommendation algorithm version."""
    return mod.RECOMMENDATION_ALGORITHM_VERSION


def _w_compute_familiar_factors(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Score the bounded pool against confirmed Taste Bank signals."""
    familiar_mod = _mods["comic_pile.familiar_weighting"]
    candidates, signals = build_familiar_inputs(
        familiar_mod.CandidateFamiliarKeys,
        familiar_mod.CreatorCreditKey,
        familiar_mod.TasteSignal,
    )
    return mod.compute_familiar_factors(candidates, signals)


def _w_aggregate_efforts(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Aggregate the reading-effort observation set."""
    observations = build_observations(_mods["comic_pile.reading_effort"].EffortObservation)
    return mod.aggregate_efforts(
        observations,
        min_trusted_sample_count=_mods[
            "comic_pile.reading_effort"
        ].DEFAULT_MIN_TRUSTED_SAMPLE_COUNT,
    )


def _w_snooze_backoff(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Compute backoff sequences and eligibility checks."""
    rng = _rng()
    snooze_counts = [rng.randint(0, 20) for _ in range(200)]
    later_counts = [rng.randint(0, 30) for _ in range(200)]
    return {
        "backoff_sequences": [mod.generate_sequence(20) for _ in range(5)],
        "eligibility_checks": [
            mod.is_eligible(sc, lc) for sc, lc in zip(snooze_counts, later_counts, strict=True)
        ],
        "backoff_values": [mod.compute_backoff_sessions(sc) for sc in snooze_counts],
    }


def _w_classify_observations(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Classify reading-effort observations against thresholds."""
    thresholds_mod = _mods["comic_pile.reading_effort_observation_rules"]
    rng = _rng()
    observations = [
        thresholds_mod.DurationObservation(duration_seconds=rng.uniform(10.0, 20000.0))
        for _ in range(5000)
    ]
    return mod.classify_reading_effort_observations(observations)


def _w_classify_hydration_reports(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Classify hydration reports into stable categories."""
    rng = _rng()
    reports = []
    for i in range(200):
        issues = []
        for j in range(rng.randint(5, 20)):
            status = rng.choice(["matched", "local-miss", "unresolved", "error", "pending"])
            issues.append({"status": status, "issue_id": 1000 + i * 20 + j})
        reports.append({"issues": issues, "summary": {"total": len(issues)}})
    return [mod.classify_hydration_report(report) for report in reports]


def _w_dice_ladder(mod: ModuleType, _mods: dict[str, ModuleType]) -> object:
    """Step through dice ladder transitions."""
    rng = _rng()
    die_sizes = [rng.choice([4, 6, 8, 10, 12, 20, 30, 50, 100]) for _ in range(5000)]
    return {
        "step_down": [mod.step_down(d) for d in die_sizes],
        "step_up": [mod.step_up(d) for d in die_sizes],
    }


WORKLOADS: tuple[Workload, ...] = (
    Workload(
        name="build_candidate_weights",
        module="comic_pile.recommendation_weights",
        call=_w_build_candidate_weights,
        describe="build_candidate_weights over 120 effort pairs x 3 bandwidth modes",
    ),
    Workload(
        name="weight_pool",
        module="comic_pile.recommendation_weighting",
        call=_w_weight_pool,
        describe="weight_pool over 120 candidate signals x 3 bandwidth/intent pairs",
    ),
    Workload(
        name="select_from_pool",
        module="comic_pile.recommendation_selection",
        call=_w_select_from_pool,
        describe="select_from_pool over pool sizes 20 and 60 x 3 control paths",
    ),
    Workload(
        name="recommendation_version",
        module="comic_pile.recommendation_version",
        call=_w_recommendation_version,
        describe="read RECOMMENDATION_ALGORITHM_VERSION (import-surface constant read)",
    ),
    Workload(
        name="compute_familiar_factors",
        module="comic_pile.familiar_weighting",
        call=_w_compute_familiar_factors,
        describe="compute_familiar_factors over 100 candidates and 24 taste signals",
    ),
    Workload(
        name="aggregate_efforts",
        module="comic_pile.reading_effort",
        call=_w_aggregate_efforts,
        describe="aggregate_efforts over 4000 reading-effort observations",
    ),
    Workload(
        name="snooze_backoff",
        module="comic_pile.snooze_backoff",
        call=_w_snooze_backoff,
        describe="snooze backoff sequence generation and eligibility over 200 checks",
    ),
    Workload(
        name="classify_observations",
        module="comic_pile.reading_effort_observation_rules",
        call=_w_classify_observations,
        describe="classify 5000 reading-effort observations against thresholds",
    ),
    Workload(
        name="classify_hydration_reports",
        module="comic_pile.comicvine_report_classification",
        call=_w_classify_hydration_reports,
        describe="classify 200 hydration reports with 5-20 issues each",
        request_shaped=False,
    ),
    Workload(
        name="dice_ladder",
        module="comic_pile.dice_ladder",
        call=_w_dice_ladder,
        describe="dice ladder step_up/step_down over 5000 transitions",
    ),
)


def request_initialization(mods: Mapping[str, ModuleType]) -> dict[str, object]:
    """Run one representative recommendation request initialization.

    This is the cold-start case that matters for serverless deployment: a fresh
    function instance imports the whole candidate surface and then runs one
    roll-shaped slice of each request-shaped workload exactly once, with nothing
    warmed. Workloads flagged ``request_shaped=False`` are offline batch work:
    they are still measured warm and cold, but charging them here would report
    offline CPU as request initialization cost.

    Args:
        mods: Already-imported candidate modules for one surface.

    Returns:
        Per-workload one-shot results, used only for equivalence checking.
    """
    return {
        workload.name: workload.call(mods[workload.module], dict(mods))
        for workload in WORKLOADS
        if workload.request_shaped
    }


# ---------------------------------------------------------------------------
# Canonical output equivalence
# ---------------------------------------------------------------------------


def _canonical(value: object) -> object:
    """Convert a workload result into a JSON-comparable structure.

    Args:
        value: Arbitrary workload return value.

    Returns:
        Structure made of dicts, lists, strings, ints, floats and bools only.
    """
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _canonical(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(item) for item in value)
    if isinstance(value, float):
        return value
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    return repr(value)


def canonical_outputs(root: str) -> dict[str, object]:
    """Compute canonical workload outputs plus surface provenance for one surface.

    Args:
        root: Directory containing the ``comic_pile`` package to exercise.

    Returns:
        ``{"outputs": {...}}`` holding canonical workload results, and
        ``{"module_files": {...}}`` recording which file actually served each
        candidate import so a comparison can prove the two surfaces differed.
    """
    mods = import_candidates(root)
    outputs: dict[str, object] = {}
    for workload in WORKLOADS:
        outputs[workload.name] = _canonical(workload.call(mods[workload.module], dict(mods)))
    outputs[REQUEST_INIT] = _canonical(request_initialization(mods))
    return {
        "outputs": outputs,
        "module_files": {
            name: os.path.basename(getattr(mod, "__file__", "") or "")
            for name, mod in mods.items()
        },
    }


# ---------------------------------------------------------------------------
# Warm measurement
# ---------------------------------------------------------------------------


def measure_warm(
    root: str,
    workload: Workload,
    mods: Mapping[str, ModuleType],
    samples: int,
    iterations: int,
) -> dict[str, object]:
    """Time repeated execution of one already-imported workload.

    Args:
        root: Import root the surface was loaded from.
        workload: Workload to time.
        mods: Already-imported candidate modules.
        samples: Number of independent timing batches.
        iterations: Workload calls inside one batch.

    Returns:
        Per-call millisecond statistics over ``samples`` observed samples.
    """
    mod = mods[workload.module]
    # Unrecorded warmup so first-call attribute lookups are not charged to the
    # first measured sample.
    for _ in range(max(1, iterations // 10)):
        workload.call(mod, dict(mods))

    per_call_ms: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        for _ in range(iterations):
            workload.call(mod, dict(mods))
        elapsed = time.perf_counter() - started
        per_call_ms.append((elapsed * 1000.0) / iterations)
    return aggregate(per_call_ms)


# ---------------------------------------------------------------------------
# Cold measurement
# ---------------------------------------------------------------------------

_CHILD_DRIVER = """
import json, sys, time
sys.path.insert(0, {bench_dir!r})
sys.path.insert(0, {root!r})
_bench_module = time.perf_counter()
import bench
_bench_ready = time.perf_counter()
payload = bench.run_child({root!r}, {workload!r})
payload["bench_import_ms"] = (_bench_ready - _bench_module) * 1000.0
sys.stdout.write(json.dumps(payload))
"""


def _child_script(root: str, workload: str) -> str:
    """Build the fresh-process driver script for one workload.

    The child imports this benchmark module, then runs exactly one workload call
    against the requested surface. It reports candidate-import time and workload
    time separately so cold-start cost can be attributed.

    Args:
        root: Import root the child must use.
        workload: Workload name the child must run once.

    Returns:
        Complete Python source for the child process.
    """
    return _CHILD_DRIVER.format(
        bench_dir=_bench_dir(),
        root=root,
        workload=workload,
    )


def run_child(root: str, workload: str) -> dict[str, object]:
    """Entry point executed inside a fresh child process for one cold sample.

    Args:
        root: Import root the child must use.
        workload: Name of the workload to run exactly once.

    Returns:
        Cold-sample payload with import and call timings plus canonical output.

    Raises:
        ValueError: If ``workload`` does not name a known workload.
    """
    by_name = {item.name: item for item in WORKLOADS}
    if workload not in by_name:
        msg = f"unknown workload: {workload}"
        raise ValueError(msg)
    selected = by_name[workload]

    started = time.perf_counter()
    mods = import_candidates(root)
    imported = time.perf_counter()
    result = selected.call(mods[selected.module], dict(mods))
    finished = time.perf_counter()

    return {
        "workload": workload,
        "module": selected.module,
        "surface": surface_name(root),
        "module_file": os.path.basename(getattr(mods[selected.module], "__file__", "") or ""),
        "candidate_import_ms": (imported - started) * 1000.0,
        "workload_ms": (finished - imported) * 1000.0,
        "output": _canonical(result),
    }


def measure_cold(root: str, workload: Workload, samples: int) -> dict[str, object]:
    """Launch one fresh interpreter process per cold sample.

    Args:
        root: Import root the child processes must use.
        workload: Workload each child runs exactly once.
        samples: Number of measured child processes.

    Returns:
        Statistics for full-process wall time, candidate import time and
        in-child workload time.
    """
    script = _child_script(root, workload.name)

    # One unrecorded child so the OS page cache and any first-run import work
    # are not charged to the measured samples.
    subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        cwd=_bench_dir(),
    )

    process_ms: list[float] = []
    import_ms: list[float] = []
    workload_ms: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            text=True,
            cwd=_bench_dir(),
        )
        process_ms.append((time.perf_counter() - started) * 1000.0)
        payload = json.loads(completed.stdout)
        import_ms.append(float(payload["candidate_import_ms"]))
        workload_ms.append(float(payload["workload_ms"]))
    return {
        "process_wall": aggregate(process_ms),
        "candidate_import": aggregate(import_ms),
        "workload": aggregate(workload_ms),
    }


def run_child_request_init(root: str) -> dict[str, object]:
    """Entry point for the fresh-process representative request initialization.

    Args:
        root: Import root the child must use.

    Returns:
        Cold-sample payload covering the whole candidate import surface plus one
        roll-shaped call of every request-shaped workload.
    """
    started = time.perf_counter()
    mods = import_candidates(root)
    imported = time.perf_counter()
    results = request_initialization(mods)
    finished = time.perf_counter()
    return {
        "workload": REQUEST_INIT,
        "surface": surface_name(root),
        "candidate_import_ms": (imported - started) * 1000.0,
        "workload_ms": (finished - imported) * 1000.0,
        "outputs": {name: _canonical(value) for name, value in results.items()},
    }


_REQUEST_INIT_DRIVER = """
import json, sys, time
sys.path.insert(0, {bench_dir!r})
sys.path.insert(0, {root!r})
_bench_module = time.perf_counter()
import bench
_bench_ready = time.perf_counter()
payload = bench.run_child_request_init({root!r})
payload["bench_import_ms"] = (_bench_ready - _bench_module) * 1000.0
sys.stdout.write(json.dumps(payload))
"""


def measure_request_initialization(root: str, samples: int) -> dict[str, object]:
    """Measure representative request initialization on one surface.

    A roll request imports the candidate surface and then does its CPU work. On
    a serverless platform this whole sequence runs once per cold instance, so it
    is measured directly rather than inferred from per-workload numbers.

    Args:
        root: Import root the child processes must use.
        samples: Number of measured child processes.

    Returns:
        Statistics for full-process wall time, surface import time and the
        in-child roll work.
    """
    script = _REQUEST_INIT_DRIVER.format(bench_dir=_bench_dir(), root=root)
    subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        check=True,
        cwd=_bench_dir(),
    )
    process_ms: list[float] = []
    import_ms: list[float] = []
    workload_ms: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=True,
            text=True,
            cwd=_bench_dir(),
        )
        process_ms.append((time.perf_counter() - started) * 1000.0)
        payload = json.loads(completed.stdout)
        import_ms.append(float(payload["candidate_import_ms"]))
        workload_ms.append(float(payload["workload_ms"]))
    return {
        "process_wall": aggregate(process_ms),
        "candidate_import": aggregate(import_ms),
        "workload": aggregate(workload_ms),
    }


def aggregate(values: Sequence[float]) -> dict[str, float | int | None]:
    """Reduce observed samples to count/extremes/spread statistics.

    Args:
        values: Observed measurements in milliseconds.

    Returns:
        Count, min, median, mean, max, standard deviation and relative
        interquartile-ish spread for the sample set. Empty input yields ``None``
        statistics rather than a fabricated zero.
    """
    if not values:
        return {
            "count": 0,
            "min_ms": None,
            "median_ms": None,
            "mean_ms": None,
            "max_ms": None,
            "stdev_ms": None,
            "spread_pct": None,
        }
    ordered = sorted(values)
    median = statistics.median(ordered)
    stdev = statistics.stdev(ordered) if len(ordered) > 1 else 0.0
    return {
        "count": len(ordered),
        "min_ms": round(min(ordered), 4),
        "median_ms": round(median, 4),
        "mean_ms": round(statistics.fmean(ordered), 4),
        "max_ms": round(max(ordered), 4),
        "stdev_ms": round(stdev, 4),
        "spread_pct": round(((max(ordered) - min(ordered)) / median) * 100.0, 2) if median else None,
    }


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------

_ELF_MACHINES = {0x03: "x86", 0x3E: "x86-64", 0xB7: "aarch64", 0x28: "arm"}
_ELF_CLASSES = {1: "ELF32", 2: "ELF64"}


def _package_version(name: str) -> str | None:
    """Return an installed distribution version, or ``None`` when absent.

    Args:
        name: Distribution name to look up.

    Returns:
        Version string, or ``None`` when the distribution is not installed.
    """
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _compiler_version() -> str:
    """Return the host C compiler version string used by the native build.

    Returns:
        First line of ``cc --version``, or a short marker when unavailable.
    """
    try:
        completed = subprocess.run(
            ["cc", "--version"], capture_output=True, check=True, text=True
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return completed.stdout.splitlines()[0].strip() if completed.stdout else "unavailable"


def collect_artifacts(root: str) -> list[dict[str, object]]:
    """Inventory the native extension artifacts produced for one surface.

    Args:
        root: Import root to inspect.

    Returns:
        One record per ``.so`` with size, ELF class and ELF machine, plus the
        ABI tag parsed from the file name.
    """
    package = os.path.join(root, "comic_pile")
    records: list[dict[str, object]] = []
    try:
        entries = sorted(os.listdir(package))
    except OSError:
        return records
    for name in entries:
        if not name.endswith(".so"):
            continue
        path = os.path.join(package, name)
        record: dict[str, object] = {
            "file": name,
            "size_bytes": os.path.getsize(path),
        }
        abi = name.split(".")[1:-1]
        record["abi_tag"] = ".".join(abi) if abi else None
        with open(path, "rb") as handle:
            header = handle.read(20)
        if header[:4] == b"\x7fELF":
            record["elf_class"] = _ELF_CLASSES.get(header[4], f"unknown({header[4]})")
            machine = int.from_bytes(header[18:20], "little")
            record["elf_machine"] = _ELF_MACHINES.get(machine, f"unknown(0x{machine:x})")
        else:
            record["elf_class"] = "not-elf"
            record["elf_machine"] = "not-elf"
        records.append(record)
    return records


def _bench_dir() -> str:
    """Return the directory holding this script.

    Returns:
        Absolute path of ``benchmark/mypyc``.
    """
    return os.path.dirname(os.path.abspath(__file__))


def _relative_root(root: str) -> str:
    """Express an import root relative to the benchmark directory.

    Reports are committed to the repository, so a recorded absolute path from
    whichever machine produced the run would be noise. Recording
    ``./source`` or ``./compiled`` keeps a checked-in report reproducible.

    Args:
        root: Absolute import root.

    Returns:
        Path relative to ``benchmark/mypyc``.
    """
    return os.path.relpath(os.path.realpath(root), _bench_dir())


def _resolve_root(recorded: str) -> str:
    """Resolve a recorded root back to an absolute path.

    Args:
        recorded: Value previously stored in a report's ``environment.root``.

    Returns:
        Absolute import root usable by child processes.
    """
    if os.path.isabs(recorded):
        return recorded
    return os.path.join(_bench_dir(), recorded)


def collect_environment(root: str) -> dict[str, object]:
    """Capture the versions and platform facts a result must be read against.

    Args:
        root: Import root being measured.

    Returns:
        Environment record embedded in every report.
    """
    artifacts = collect_artifacts(root)
    return {
        "surface": surface_name(root),
        "root": _relative_root(root),
        "python_version": platform.python_version(),
        "python_implementation": sys.implementation.name,
        "python_full_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "mypy_version": _package_version("mypy"),
        "setuptools_version": _package_version("setuptools"),
        "c_compiler": _compiler_version(),
        "seed": SEED,
        "artifacts": artifacts,
        "artifact_total_bytes": sum(int(item["size_bytes"]) for item in artifacts),
        "source_total_bytes": _source_total_bytes(root),
    }


def _source_total_bytes(root: str) -> int:
    """Total byte size of the pure-Python modules shadowed by artifacts.

    Args:
        root: Import root to inspect.

    Returns:
        Summed size of the candidate ``.py`` files on this surface.
    """
    package = os.path.join(root, "comic_pile")
    total = 0
    try:
        entries = os.listdir(package)
    except OSError:
        return total
    for name in entries:
        if name.endswith(".py"):
            total += os.path.getsize(os.path.join(package, name))
    return total


# ---------------------------------------------------------------------------
# Measure mode
# ---------------------------------------------------------------------------


def run_measure(root: str, warm_samples: int, warm_iterations: int, cold_samples: int) -> dict[
    str, object
]:
    """Measure every workload on one surface.

    Args:
        root: Import root to measure.
        warm_samples: Independent warm batches per workload.
        warm_iterations: Workload calls inside one warm batch.
        cold_samples: Fresh child processes per cold workload.

    Returns:
        Full JSON-serializable report for one surface.
    """
    mods = import_candidates(root)
    results: list[dict[str, object]] = []
    for workload in WORKLOADS:
        results.append(
            {
                "workload": workload.name,
                "module": workload.module,
                "describe": workload.describe,
                "module_file": os.path.basename(getattr(mods[workload.module], "__file__", "") or ""),
                "warm": measure_warm(root, workload, mods, warm_samples, warm_iterations),
                "cold": measure_cold(root, workload, cold_samples),
            }
        )
    return {
        "benchmark": "mypyc-cpu-evaluation",
        "issue": 3258,
        "environment": collect_environment(root),
        "configuration": {
            "warm_samples": warm_samples,
            "warm_iterations": warm_iterations,
            "cold_samples": cold_samples,
            "workload_sizes": {
                "effort_count": EFFORT_COUNT,
                "signal_count": SIGNAL_COUNT,
                "observation_count": OBSERVATION_COUNT,
                "familiar_candidate_count": FAMILIAR_CANDIDATE_COUNT,
                "familiar_signal_count": FAMILIAR_SIGNAL_COUNT,
                "pool_sizes": list(POOL_SIZES),
            },
        },
        "request_initialization": measure_request_initialization(root, cold_samples),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------


def _scalar_equal(left: object, right: object, *, numeric: bool) -> bool:
    """Compare two leaves, optionally treating ``0`` and ``0.0`` as equal.

    Args:
        left: Baseline leaf value.
        right: Candidate leaf value.
        numeric: When true, compare int/float leaves by numeric value.

    Returns:
        Whether the leaves match under the requested comparison.
    """
    numeric_leaves = (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    )
    if numeric and numeric_leaves:
        return float(left) == float(right)
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _differences(left: object, right: object, path: str = "$", *, numeric: bool = True) -> list[str]:
    """Collect paths whose canonical encodings differ between two surfaces.

    Args:
        left: Baseline value.
        right: Candidate value.
        path: JSON path prefix used in the reported differences.
        numeric: When true, ``0`` and ``0.0`` compare equal. When false the
            comparison is strict, so an int/float representation change is
            reported rather than silently accepted.

    Returns:
        Difference descriptions in traversal order.
    """
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        found: list[str] = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                found.append(f"{path}.{key}: present on only one surface")
            else:
                found.extend(_differences(left[key], right[key], f"{path}.{key}", numeric=numeric))
        return found
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return [f"{path}: length {len(left)} != {len(right)}"]
        found = []
        for index, (one, two) in enumerate(zip(left, right, strict=True)):
            found.extend(_differences(one, two, f"{path}[{index}]", numeric=numeric))
        return found
    if _scalar_equal(left, right, numeric=numeric):
        return []
    if type(left) is not type(right):
        return [f"{path}: {left!r} ({type(left).__name__}) != {right!r} ({type(right).__name__})"]
    return [f"{path}: {left!r} != {right!r}"]


def _ratio(baseline: float | None, candidate: float | None) -> float | None:
    """Return ``baseline / candidate``, or ``None`` when it is undefined.

    Args:
        baseline: Baseline measurement.
        candidate: Candidate measurement.

    Returns:
        Speedup factor, or ``None`` when either side is missing or zero.
    """
    if not baseline or candidate is None:
        return None
    return baseline / candidate


def compare_reports(baseline_path: str, candidate_path: str) -> dict[str, object]:
    """Compare two surface reports and check output equivalence.

    Args:
        baseline_path: JSON report produced by ``--root source``.
        candidate_path: JSON report produced by ``--root compiled``.

    Returns:
        Comparison payload with per-workload deltas, equivalence findings and
        artifact summary.
    """
    with open(baseline_path, encoding="utf-8") as handle:
        baseline = json.load(handle)
    with open(candidate_path, encoding="utf-8") as handle:
        candidate = json.load(handle)

    baseline_results = {item["workload"]: item for item in baseline["results"]}
    candidate_results = {item["workload"]: item for item in candidate["results"]}

    def _request_row(payload: Mapping[str, object]) -> dict[str, object]:
        """Build the representative-request row from two surfaces' payloads."""
        base_cold = payload["baseline"]
        cand_cold = payload["candidate"]
        base_wall = base_cold["process_wall"]["median_ms"]
        cand_wall = cand_cold["process_wall"]["median_ms"]
        base_import = base_cold["candidate_import"]["median_ms"]
        cand_import = cand_cold["candidate_import"]["median_ms"]
        base_work = base_cold["workload"]["median_ms"]
        cand_work = cand_cold["workload"]["median_ms"]
        return {
            "workload": REQUEST_INIT,
            "module": "<all six candidates>",
            "warm_cpython_ms": None,
            "warm_mypyc_ms": None,
            "warm_speedup_x": None,
            "warm_spread_cpython_pct": None,
            "warm_spread_mypyc_pct": None,
            "cold_spread_cpython_pct": base_cold["process_wall"]["spread_pct"],
            "cold_spread_mypyc_pct": cand_cold["process_wall"]["spread_pct"],
            "cold_cpython_ms": base_wall,
            "cold_mypyc_ms": cand_wall,
            "cold_delta_ms": (
                round(cand_wall - base_wall, 3)
                if isinstance(base_wall, (int, float)) and isinstance(cand_wall, (int, float))
                else None
            ),
            "cold_import_cpython_ms": base_import,
            "cold_import_mypyc_ms": cand_import,
            "cold_import_delta_ms": (
                round(cand_import - base_import, 3)
                if isinstance(base_import, (int, float))
                and isinstance(cand_import, (int, float))
                else None
            ),
            "cold_work_cpython_ms": base_work,
            "cold_work_mypyc_ms": cand_work,
        }

    request_row = _request_row(
        {
            "baseline": baseline["request_initialization"],
            "candidate": candidate["request_initialization"],
        }
    )

    rows: list[dict[str, object]] = []
    for name, base_row in baseline_results.items():
        cand_row = candidate_results.get(name)
        if cand_row is None:
            continue
        warm_base = base_row["warm"]["median_ms"]
        warm_cand = cand_row["warm"]["median_ms"]
        cold_base = base_row["cold"]["process_wall"]["median_ms"]
        cold_cand = cand_row["cold"]["process_wall"]["median_ms"]
        import_base = base_row["cold"]["candidate_import"]["median_ms"]
        import_cand = cand_row["cold"]["candidate_import"]["median_ms"]
        rows.append(
            {
                "workload": name,
                "module": base_row["module"],
                "warm_cpython_ms": warm_base,
                "warm_mypyc_ms": warm_cand,
                "warm_speedup_x": (
                    round(_ratio(warm_base, warm_cand), 3) if warm_base and warm_cand else None
                ),
                "warm_spread_cpython_pct": base_row["warm"]["spread_pct"],
                "warm_spread_mypyc_pct": cand_row["warm"]["spread_pct"],
                "cold_spread_cpython_pct": base_row["cold"]["process_wall"]["spread_pct"],
                "cold_spread_mypyc_pct": cand_row["cold"]["process_wall"]["spread_pct"],
                "cold_cpython_ms": cold_base,
                "cold_mypyc_ms": cold_cand,
                "cold_delta_ms": (
                    round(cold_cand - cold_base, 3)
                    if isinstance(cold_base, (int, float))
                    and isinstance(cold_cand, (int, float))
                    else None
                ),
                "cold_import_cpython_ms": import_base,
                "cold_import_mypyc_ms": import_cand,
                "cold_import_delta_ms": (
                    round(import_cand - import_base, 3)
                    if isinstance(import_base, (int, float))
                    and isinstance(import_cand, (int, float))
                    else None
                ),
            }
        )

    baseline_root = _resolve_root(str(baseline["environment"]["root"]))
    candidate_root = _resolve_root(str(candidate["environment"]["root"]))
    base_outputs = _child_outputs(baseline_root)
    cand_outputs = _child_outputs(candidate_root)
    value_diffs = _differences(
        base_outputs["outputs"], cand_outputs["outputs"], numeric=True
    )
    repr_diffs = _differences(
        base_outputs["outputs"], cand_outputs["outputs"], numeric=False
    )

    base_files = base_outputs["module_files"]
    cand_files = cand_outputs["module_files"]
    native_served = sorted(
        name for name, path in cand_files.items() if str(path).endswith(".so")
    )
    python_served = sorted(
        name for name, path in base_files.items() if str(path).endswith(".py")
    )
    provenance = {
        "baseline_module_files": base_files,
        "candidate_module_files": cand_files,
        "baseline_served_python": len(python_served) == len(base_files),
        "candidate_served_native": len(native_served) == len(cand_files),
        "distinct_surfaces": base_files != cand_files,
    }

    return {
        "issue": 3258,
        "baseline_environment": baseline["environment"],
        "candidate_environment": candidate["environment"],
        "configuration": baseline["configuration"],
        "rows": [*rows, request_row],
        "provenance": provenance,
        "equivalence": {
            "surfaces_distinct": provenance["distinct_surfaces"],
            "identical_including_representation": not repr_diffs,
            "identical_numerically": not value_diffs,
            "representation_only_differences": sorted(set(repr_diffs) - set(value_diffs)),
            "value_differences": value_diffs,
        },
    }


def _child_outputs(root: str) -> dict[str, object]:
    """Compute canonical outputs in a fresh process pinned to one surface.

    Args:
        root: Import root to use.

    Returns:
        Canonical outputs for that surface, or a marker describing the failure
        when the surface cannot be imported.
    """
    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {_bench_dir()!r})\n"
        f"sys.path.insert(0, {root!r})\n"
        "import bench\n"
        "sys.stdout.write(json.dumps(bench.canonical_outputs(sys.argv[1]), "
        "sort_keys=True, default=repr))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, root],
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(report: dict[str, object]) -> str:
    """Render a comparison report as a decision-ready Markdown table.

    Args:
        report: Payload produced by :func:`compare_reports`.

    Returns:
        Markdown document with the measured warm/cold deltas, equivalence
        outcome and artifact inventory.
    """
    baseline_env = report["baseline_environment"]
    candidate_env = report["candidate_environment"]
    equivalence = report["equivalence"]
    request_row = next(
        row for row in report["rows"] if row["workload"] == REQUEST_INIT
    )

    lines: list[str] = []
    lines.append("# mypyc evaluation - measured comparison (issue #3258)")
    lines.append("")
    lines.append(f"- Interpreter: CPython {baseline_env['python_version']} "
                 f"({baseline_env['python_implementation']})")
    lines.append(f"- Platform: {baseline_env['platform']} / {baseline_env['machine']}")
    lines.append(f"- mypy / mypyc: {baseline_env['mypy_version']}")
    lines.append(f"- C compiler: {baseline_env['c_compiler']}")
    configuration = report["configuration"]
    lines.append(
        f"- Warm: {configuration['warm_samples']} samples x "
        f"{configuration['warm_iterations']} calls; "
        f"cold: {configuration['cold_samples']} fresh processes"
    )
    lines.append(f"- Seed: {baseline_env['seed']}")
    lines.append("")
    lines.append("## Warm execution (median of observed samples)")
    lines.append("")
    lines.append("| Workload | CPython ms | mypyc ms | Speedup | Warm spread CPython | Warm spread mypyc |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in report["rows"]:
        if row["workload"] == REQUEST_INIT:
            continue
        lines.append(
            f"| `{row['workload']}` | {row['warm_cpython_ms']} | {row['warm_mypyc_ms']} "
            f"| {row['warm_speedup_x']}x | {row['warm_spread_cpython_pct']}% "
            f"| {row['warm_spread_mypyc_pct']}% |"
        )
    lines.append("")
    lines.append("## Cold start (fresh process wall time, median)")
    lines.append("")
    lines.append(
        "`request_initialization` imports the whole candidate surface and then runs "
        "one roll-shaped call of every request-shaped workload, which is the sequence "
        "a serverless cold instance actually pays. Offline batch workloads "
        "(`request_shaped=False`) are measured warm and cold but are not charged to "
        "this number. The per-workload rows import the same surface and add a single "
        "workload call."
    )
    lines.append("")
    lines.append("| Workload | CPython ms | mypyc ms | Delta ms | Import delta ms |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for row in report["rows"]:
        lines.append(
            f"| `{row['workload']}` | {row['cold_cpython_ms']} | {row['cold_mypyc_ms']} "
            f"| {row['cold_delta_ms']} | {row['cold_import_delta_ms']} |"
        )
    lines.append("")
    lines.append(
        f"- Representative request wall time: CPython "
        f"{request_row['cold_cpython_ms']} ms, mypyc {request_row['cold_mypyc_ms']} ms "
        f"({request_row['cold_delta_ms']} ms)"
    )
    lines.append(
        f"- Representative request in-process work: CPython "
        f"{request_row['cold_work_cpython_ms']} ms, mypyc "
        f"{request_row['cold_work_mypyc_ms']} ms"
    )
    lines.append(
        f"- Representative request surface import: CPython "
        f"{request_row['cold_import_cpython_ms']} ms, mypyc "
        f"{request_row['cold_import_mypyc_ms']} ms "
        f"({request_row['cold_import_delta_ms']} ms)"
    )
    lines.append("")
    lines.append("## Output equivalence")
    lines.append("")
    provenance = report["provenance"]
    lines.append(
        f"- Baseline served pure-Python modules: "
        f"**{provenance['baseline_served_python']}**; candidate served native "
        f"extensions: **{provenance['candidate_served_native']}**; surfaces "
        f"distinct: **{equivalence['surfaces_distinct']}**"
    )
    lines.append(f"- Numerically identical: **{equivalence['identical_numerically']}**")
    lines.append(
        f"- Byte-identical including representation: "
        f"**{equivalence['identical_including_representation']}**"
    )
    if equivalence["representation_only_differences"]:
        representation = equivalence["representation_only_differences"]
        lines.append(
            f"- Representation-only differences "
            f"({len(representation)} total; value-equal, JSON type differs):"
        )
        for difference in representation[:_MAX_RENDERED_DIFFERENCES]:
            lines.append(f"  - `{difference}`")
        if len(representation) > _MAX_RENDERED_DIFFERENCES:
            lines.append(
                f"  - ... and {len(representation) - _MAX_RENDERED_DIFFERENCES} more"
            )
    if equivalence["value_differences"]:
        lines.append("- Value differences:")
        for difference in equivalence["value_differences"]:
            lines.append(f"  - `{difference}`")
    lines.append("")
    lines.append("## Native artifacts")
    lines.append("")
    artifacts = candidate_env["artifacts"]
    lines.append(f"- Count: {len(artifacts)}")
    lines.append(f"- Total size: {candidate_env['artifact_total_bytes']} bytes")
    for artifact in artifacts:
        lines.append(
            f"  - `{artifact['file']}` {artifact['size_bytes']} bytes, "
            f"{artifact['elf_class']}/{artifact['elf_machine']}, abi `{artifact['abi_tag']}`"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark in measure or compare mode.

    Args:
        argv: Optional argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit status.
    """
    here = _bench_dir()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        choices=("source", "compiled"),
        help="Surface to measure: 'source' (CPython .py) or 'compiled' (mypyc .so).",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASELINE_JSON", "CANDIDATE_JSON"),
        help="Compare a CPython report against a mypyc report instead of measuring.",
    )
    parser.add_argument("--warm-samples", type=int, default=WARM_SAMPLES)
    parser.add_argument("--warm-iterations", type=int, default=WARM_ITERATIONS)
    parser.add_argument("--cold-samples", type=int, default=COLD_SAMPLES)
    parser.add_argument("--output", help="Optional path to write the report to.")
    args = parser.parse_args(argv)

    if bool(args.compare) == bool(args.root):
        parser.error("pass exactly one of --root or --compare")

    if args.compare:
        report = compare_reports(args.compare[0], args.compare[1])
        rendered = render_markdown(report)
        print(rendered)
        if args.output:
            _write(args.output, rendered + "\n")
        equivalence = report["equivalence"]
        return 0 if equivalence["surfaces_distinct"] and equivalence["identical_numerically"] else 1

    report = run_measure(
        os.path.join(here, args.root), args.warm_samples, args.warm_iterations, args.cold_samples
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        _write(args.output, rendered + "\n")
    return 0


def _write(path: str, text: str) -> None:
    """Write report text, creating parent directories when needed.

    Args:
        path: Destination path.
        text: Full file contents.
    """
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


if __name__ == "__main__":
    raise SystemExit(main())