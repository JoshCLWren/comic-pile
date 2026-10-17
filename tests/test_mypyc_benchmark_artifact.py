"""Guard the issue #3258 mypyc evaluation artifact.

The evaluation lives in ``benchmark/mypyc/``. It measures copies of the
production recommendation modules rather than the modules themselves, so the
copies can shadow imports at runtime without touching ``comic_pile/``. That is
only safe while the copies are byte-identical to production, so these tests
pin the copies, pin the module set the harness measures against the set the
build compiles, and pin the measurement helpers the recorded results depend on.

These tests deliberately do **not** import ``bench`` at module scope: the
harness is a benchmark script, not a runtime dependency. Nothing in ``app/``,
``comic_pile/``, ``scripts/``, ``tests/``, ``alembic/`` or ``.github/`` imports
``benchmark/``, and a test that accidentally made that true would turn an
evaluation-only tree into a production dependency.
"""

from __future__ import annotations

import ast
import filecmp
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO_ROOT / "benchmark" / "mypyc"
SOURCE_DIR = BENCH_DIR / "source" / "comic_pile"
COMPILED_DIR = BENCH_DIR / "compiled" / "comic_pile"
RESULTS_DIR = BENCH_DIR / "results"


def _load_bench():
    """Import ``benchmark/mypyc/bench.py`` under a private module name.

    The module is registered in ``sys.modules`` before execution because
    ``dataclasses`` resolves field defaults through the defining module's
    globals, which requires the entry to already exist.

    Returns:
        The imported benchmark module.
    """
    name = "mypyc_bench_under_test"
    spec = importlib.util.spec_from_file_location(name, BENCH_DIR / "bench.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _setup_module_list() -> list[str]:
    """Return the module paths ``setup.py`` hands to ``mypycify``.

    Returns:
        Relative module paths in declaration order.
    """
    tree = ast.parse((BENCH_DIR / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Tuple):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "COMPILED_MODULES":
                return [ast.literal_eval(element) for element in node.value.elts]
    raise AssertionError("setup.py no longer declares COMPILED_MODULES")


def test_benchmark_copies_match_production_modules() -> None:
    """Both benchmark surfaces must be byte-identical to the shipped modules."""
    copied = sorted(path.name for path in SOURCE_DIR.glob("*.py") if path.name != "__init__.py")
    assert copied, "benchmark/mypyc/source/comic_pile is missing module copies"
    for name in copied:
        production = REPO_ROOT / "comic_pile" / name
        assert production.is_file(), f"comic_pile/{name} no longer exists"
        for surface in (SOURCE_DIR, COMPILED_DIR):
            assert surface.joinpath(name).is_file(), f"{surface.name}/{name} is missing"
            assert filecmp.cmp(production, surface / name, shallow=False), (
                f"benchmark/mypyc/{surface.name}/comic_pile/{name} has drifted from "
                f"comic_pile/{name}. The evaluation compares benchmark copies, so a "
                f"drift makes every recorded result describe code that does not ship."
            )


def test_setup_compiles_exactly_the_measured_modules() -> None:
    """``setup.py`` must compile the same module set ``bench.py`` measures."""
    bench = _load_bench()
    assert sorted(_setup_module_list()) == sorted(
        f"compiled/comic_pile/{name.rsplit('.', 1)[-1]}.py" for name in bench.MODULES
    )
    compiled_names = {path.rsplit("/", 1)[-1][:-3] for path in _setup_module_list()}
    assert compiled_names == {name.rsplit(".", 1)[-1] for name in bench.MODULES}


def test_setup_declares_the_inplace_package_directory() -> None:
    """``package_dir`` must point at ``compiled/`` or the in-place copy fails.

    Without it setuptools resolves the extension package to ``comic_pile/``
    relative to the current directory, and ``build_ext --inplace`` aborts with
    "could not create ...". That failure mode is invisible until someone runs
    the documented build command.
    """
    tree = ast.parse((BENCH_DIR / "setup.py").read_text(encoding="utf-8"))
    package_dirs = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setup"
        for keyword in node.keywords
        if keyword.arg == "package_dir"
    ]
    assert len(package_dirs) == 1
    assert ast.literal_eval(package_dirs[0]) == {"": "compiled"}


def test_bench_reports_every_candidate_module() -> None:
    """Every compiled candidate must have a workload and a recorded result."""
    bench = _load_bench()
    workload_modules = {workload.module for workload in bench.WORKLOADS}
    assert workload_modules == set(bench.MODULES)
    assert len(bench.WORKLOADS) == len({workload.name for workload in bench.WORKLOADS})


def test_cold_measurement_starts_before_the_candidate_import() -> None:
    """The cold driver must begin timing before anything imports a candidate.

    The previous harness set its start timestamp *after* the candidate import,
    so the "cold" number measured only workload construction. Any future
    restructuring that moves the import ahead of the clock silently reintroduces
    that, so pin the ordering.
    """
    source = (BENCH_DIR / "bench.py").read_text(encoding="utf-8")
    for driver in ("_CHILD_DRIVER", "_REQUEST_INIT_DRIVER"):
        block = source.split(f"{driver} = ", 1)[1]
        body = block.split('"""', 2)[1]
        clock = body.index("time.perf_counter()")
        assert "import bench" in body
        assert body.index("import bench") > clock, f"{driver} imports bench before starting the clock"
        assert "sys.path.insert(0, {root!r})" in body


def test_warm_measurement_records_real_samples_not_one_restated() -> None:
    """Warm samples must come from independent timing batches.

    Returning ``[per_call] * iterations`` makes min, median and max identical by
    construction, which is how the first version of this harness reported zero
    variability. Each measured sample must come from its own ``perf_counter``
    interval.
    """
    bench = _load_bench()
    source = Path(bench.__file__).read_text(encoding="utf-8")
    warm_body = source.split("def measure_warm(", 1)[1].split("\ndef ", 1)[0]
    assert warm_body.count("started = time.perf_counter()") == 1
    assert "for _ in range(samples):" in warm_body
    assert "* iterations" not in warm_body


def test_aggregate_does_not_fabricate_statistics() -> None:
    """Empty sample sets must report ``None`` statistics, not zero."""
    bench = _load_bench()
    empty = bench.aggregate([])
    assert empty["count"] == 0
    assert all(
        value is None
        for key, value in empty.items()
        if key not in {"count"}
    )

    single = bench.aggregate([4.0])
    assert single["count"] == 1
    assert single["median_ms"] == 4.0
    assert single["stdev_ms"] == 0.0
    assert single["spread_pct"] == 0.0

    varied = bench.aggregate([1.0, 3.0])
    assert varied["min_ms"] == 1.0
    assert varied["max_ms"] == 3.0
    assert varied["median_ms"] == 2.0
    assert varied["mean_ms"] == 2.0
    assert varied["stdev_ms"] == pytest.approx(1.4142, abs=1e-9)
    assert varied["spread_pct"] == pytest.approx(100.0)


def test_numeric_comparison_accepts_zero_but_strict_comparison_does_not() -> None:
    """Representation drift must be detectable, not silently equal.

    ``0`` and ``0.0`` are the observed mypyc/CPython divergence for a
    zero-match familiar bonus. The numeric comparison must accept them and the
    strict comparison must report them, otherwise the equivalence result cannot
    describe that finding.
    """
    bench = _load_bench()
    assert bench._differences({"bonus": 0}, {"bonus": 0.0}, numeric=True) == []
    strict = bench._differences({"bonus": 0}, {"bonus": 0.0}, numeric=False)
    assert len(strict) == 1
    assert "int" in strict[0] and "float" in strict[0]


def test_difference_reporter_handles_structure_and_type_changes() -> None:
    """Structural, key-set and scalar type changes must all be reported."""
    bench = _load_bench()
    assert bench._differences({"a": [1, 2]}, {"a": [1, 2, 3]}) == ["$.a: length 2 != 3"]
    assert bench._differences({"a": 1}, {"b": 1}) == [
        "$.a: present on only one surface",
        "$.b: present on only one surface",
    ]
    assert bench._differences({"a": None}, {"a": "x"}) == [
        "$.a: None (NoneType) != 'x' (str)"
    ]
    assert bench._differences({"a": [1, {"b": 2}]}, {"a": [1, {"b": 3}]}) == ["$.a[1].b: 2 != 3"]
    assert bench._differences({"a": 1}, {"a": 1}) == []


def test_recorded_results_carry_the_environment_they_claim() -> None:
    """Committed reports must name CPython 3.14 and real sample counts."""
    for name in ("cpython", "mypyc"):
        path = RESULTS_DIR / f"{name}.json"
        assert path.is_file(), f"missing recorded report {path}"
        report = json.loads(path.read_text(encoding="utf-8"))
        environment = report["environment"]
        assert environment["python_version"].startswith("3.14")
        assert environment["python_implementation"] == "cpython"
        assert environment["machine"] == "x86_64"
        assert environment["mypy_version"], "record the mypy/mypyc version used"
        assert environment["c_compiler"], "record the C compiler used"
        assert environment["seed"] == 20261017
        configuration = report["configuration"]
        assert configuration["warm_samples"] >= 5
        assert configuration["cold_samples"] >= 5
        assert len(report["results"]) == 6
        for row in report["results"]:
            assert row["warm"]["count"] == configuration["warm_samples"]
            assert row["cold"]["process_wall"]["count"] == configuration["cold_samples"]
            assert row["cold"]["process_wall"]["stdev_ms"] is not None
        request = report["request_initialization"]
        assert request["process_wall"]["count"] == configuration["cold_samples"]

    compiled = json.loads((RESULTS_DIR / "mypyc.json").read_text(encoding="utf-8"))
    baseline = json.loads((RESULTS_DIR / "cpython.json").read_text(encoding="utf-8"))
    assert compiled["environment"]["surface"] == "mypyc"
    assert baseline["environment"]["surface"] == "cpython"
    assert compiled["environment"]["artifact_total_bytes"] > 0
    assert baseline["environment"]["artifact_total_bytes"] == 0


def test_recorded_comparison_documents_the_decision_inputs() -> None:
    """The committed comparison must carry the tables and equivalence verdict."""
    comparison = (RESULTS_DIR / "comparison.md").read_text(encoding="utf-8")
    for heading in (
        "# mypyc evaluation - measured comparison (issue #3258)",
        "## Warm execution",
        "## Cold start",
        "## Output equivalence",
        "## Native artifacts",
        "request_initialization",
    ):
        assert heading in comparison, f"comparison.md no longer reports {heading!r}"
    assert "Numerically identical: **True**" in comparison


def test_evaluation_tree_is_not_reachable_from_production() -> None:
    """No production, script, test, migration or CI file may import the harness."""
    surfaces = ("app", "comic_pile", "scripts", "alembic", ".github", "Dockerfile", "Dockerfile.ci")
    offenders: list[str] = []
    for surface in surfaces:
        path = REPO_ROOT / surface
        candidates = sorted(path.rglob("*.py")) if path.is_dir() else ([path] if path.is_file() else [])
        for candidate in candidates:
            text = candidate.read_text(encoding="utf-8", errors="ignore")
            if "benchmark/mypyc" in text or "benchmark.mypyc" in text:
                offenders.append(str(candidate.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"benchmark/mypyc must stay evaluation-only, but is referenced from {offenders}"
    )


def test_evaluation_tree_is_not_built_by_the_container_image() -> None:
    """The Docker build must not copy or compile the evaluation tree."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "benchmark" not in dockerfile
    assert "mypyc" not in dockerfile


def test_harness_reports_a_versioned_json_report_for_both_surfaces() -> None:
    """``--root`` must reject unknown surfaces and require exactly one mode."""
    bench = _load_bench()
    with pytest.raises(SystemExit):
        bench.main(["--root", "nonsense"])
    with pytest.raises(SystemExit):
        bench.main([])
    with pytest.raises(SystemExit):
        bench.main(["--root", "source", "--compare", "a.json", "b.json"])


def test_surface_classification_reflects_presence_of_native_artifacts(tmp_path: Path) -> None:
    """A root without ``.so`` files is the CPython surface, with them, mypyc."""
    bench = _load_bench()
    package = tmp_path / "comic_pile"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    assert bench.surface_name(str(tmp_path)) == "cpython"
    (package / "reading_effort.cpython-314-x86_64-linux-gnu.so").write_bytes(b"")
    assert bench.surface_name(str(tmp_path)) == "mypyc"


def test_artifact_inventory_parses_elf_and_abi_tag(tmp_path: Path) -> None:
    """Artifact records must expose size, ELF class/machine and ABI tag."""
    bench = _load_bench()
    package = tmp_path / "comic_pile"
    package.mkdir()
    elf = bytearray(20)
    elf[0:4] = b"\x7fELF"
    elf[4] = 2  # ELFCLASS64
    elf[18:20] = (0x3E).to_bytes(2, "little")  # EM_X86_64
    name = "reading_effort.cpython-314-x86_64-linux-gnu.so"
    (package / name).write_bytes(bytes(elf))
    (package / "reading_effort.py").write_text("x = 1\n", encoding="utf-8")

    records = bench.collect_artifacts(str(tmp_path))
    assert len(records) == 1
    record = records[0]
    assert record["file"] == name
    assert record["size_bytes"] == 20
    assert record["abi_tag"] == "cpython-314-x86_64-linux-gnu"
    assert record["elf_class"] == "ELF64"
    assert record["elf_machine"] == "x86-64"


def test_readme_documents_the_reproduction_recipe() -> None:
    """The reproduction steps must stay present and match the real CLI."""
    readme = (BENCH_DIR / "README.md").read_text(encoding="utf-8")
    for fragment in (
        "setup.py build_ext --inplace",
        "bench.py --root source",
        "bench.py --root compiled",
        "bench.py --compare",
    ):
        assert fragment in readme, f"README no longer documents {fragment!r}"


def test_bench_module_imports_without_the_third_party_toolchain() -> None:
    """The harness must stay standard-library only so either surface can run it."""
    tree = ast.parse((BENCH_DIR / "bench.py").read_text(encoding="utf-8"))
    allowed = {
        "__future__",
        "argparse",
        "ast",
        "importlib",
        "json",
        "os",
        "platform",
        "random",
        "statistics",
        "subprocess",
        "sys",
        "time",
        "collections.abc",
        "dataclasses",
        "importlib.metadata",
        "types",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= allowed, f"benchmark harness gained non-stdlib imports: {imported - allowed}"


def test_compiled_surface_has_no_stray_artifacts_committed() -> None:
    """Native artifacts are build output and must never be committed.

    This asks git rather than the filesystem: running the documented build
    locally leaves ``.so`` files and ``build/`` behind on purpose, and that is
    fine. What must not exist is a tracked artifact.
    """
    tracked = _git_ls_files()
    artifacts = [path for path in tracked if path.endswith(".so") or "/build/" in path]
    assert artifacts == [], f"compiled artifacts must stay untracked: {artifacts}"
    assert not any(
        path.startswith("benchmark/mypyc/build/") for path in tracked
    ), "benchmark/mypyc/build is build output"


def _git_ls_files() -> list[str]:
    """Return tracked repository paths, or an empty list outside a checkout."""
    try:
        completed = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            check=True,
            text=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return completed.stdout.split()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX path handling")
def test_recorded_results_paths_are_repo_relative() -> None:
    """Committed reports must not leak the machine that produced them."""
    for path in RESULTS_DIR.glob("*.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        recorded = report["environment"]["root"]
        assert not Path(recorded).is_absolute(), f"{path.name} records an absolute root"
        assert recorded in {"source", "compiled"}


def test_setup_pins_the_build_options_the_recorded_results_used() -> None:
    """``mypycify`` options must match what produced ``results/``.

    The committed reports were measured with ``opt_level="3"`` and
    ``separate=True``. Changing either changes the artifacts and invalidates
    every recorded number, so pin them here rather than discovering the drift
    when someone re-runs the benchmark and gets different tables.
    """
    tree = ast.parse((BENCH_DIR / "setup.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "mypycify"
    ]
    assert len(calls) == 1
    options = {keyword.arg: keyword.value for keyword in calls[0].keywords if keyword.arg}
    assert ast.literal_eval(options["opt_level"]) == "3"
    assert ast.literal_eval(options["separate"]) is True
    assert ast.literal_eval(options["multi_file"]) is False
    assert ast.literal_eval(options["debug_level"]) == "0"


def test_build_would_compile_into_the_compiled_surface() -> None:
    """Every declared module must exist under ``compiled/comic_pile/``."""
    for relative in _setup_module_list():
        path = BENCH_DIR / relative
        assert path.is_file(), f"setup.py compiles a missing module: {relative}"
        assert path.parent == COMPILED_DIR


def test_build_is_isolated_from_the_repository_mypy_configuration() -> None:
    """A local mypy config must stop the build aborting on unused sections.

    ``mypycify`` walks up from the working directory to find mypy
    configuration. Without ``benchmark/mypyc/mypy.ini`` the build inherits the
    repository root ``mypy.ini``, whose ``warn_unused_configs = True`` turns
    "unused section(s)" into an error-channel message and makes mypycify abort
    before compiling anything. Losing this file silently breaks the documented
    build command.
    """
    local_config = BENCH_DIR / "mypy.ini"
    assert local_config.is_file(), (
        "benchmark/mypyc/mypy.ini is required: without it the mypyc build inherits "
        "the repository mypy.ini and aborts on unused-section notes"
    )
    text = local_config.read_text(encoding="utf-8")
    assert "strict = True" in text
    assert "warn_unused_configs = False" in text


def test_recorded_decision_document_states_the_verdict() -> None:
    """The evaluation must record a decision and the measured inputs behind it."""
    results = (BENCH_DIR / "RESULTS.md").read_text(encoding="utf-8")
    assert "Decision: no-go" in results
    for heading in (
        "## What was measured, and how",
        "## Warm execution",
        "## Cold start",
        "## Output equivalence",
        "## Packaging and deployment",
        "## Cost / benefit summary",
    ):
        assert heading in results, f"RESULTS.md no longer reports {heading!r}"
    assert "3.14" in results
    assert "cp314-cp314-linux_x86_64" in results


def test_recorded_decision_is_not_a_production_runtime_switch() -> None:
    """The evaluation must not have touched any runtime or deployment file."""
    protected = ("app/", "comic_pile/", "alembic/", "api/", "Dockerfile", "vercel.json", ".github/")
    offenders = [path for path in _git_ls_files() if path.startswith(protected) and _is_new_in_head(path)]
    assert offenders == [], f"issue #3258 forbids production changes, but found {offenders}"


def _is_new_in_head(path: str) -> bool:
    """Return whether ``path`` was added or modified relative to ``main``.

    Files that already shipped before this branch are not this evaluation's
    doing. When the base ref is unavailable, fall back to "changed in the
    working tree", which is the conservative answer.
    """
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", path],
            capture_output=True,
            check=True,
            text=True,
            cwd=REPO_ROOT,
        )
    except (OSError, subprocess.CalledProcessError):
        return True
    return path in completed.stdout.split()