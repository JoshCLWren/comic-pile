"""Unit tests for OpenCode CLI factory catalog discovery and retirement."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
FIXTURES = ROOT / "tests" / "fixtures" / "opencode-catalog"


def _load(name: str, filename: str) -> ModuleType:
    """Load a ``.github/scripts`` module without packaging that tree."""
    sys.path.insert(0, str(SCRIPTS))
    path = SCRIPTS / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ROSTER = _load("factory_roster_discovery_test", "factory_roster.py")
CATALOG = _load("factory_model_catalog_test", "factory_model_catalog.py")
RETIRE = _load("factory_model_retirement_test", "factory_model_retirement.py")


def _row(
    worker: str,
    source: str,
    model: str,
    minute: str = "5",
) -> dict[str, str]:
    """Build one roster row for planner tests."""
    return {
        "worker": worker,
        "source": source,
        "model": model,
        "minute": minute,
        "scheduler": "dispatcher",
        "display_name": model,
    }


def test_committed_lock_matches_live_roster() -> None:
    """The generated expected-worker lock must stay in sync with the TSV."""
    rows = ROSTER.load_roster_rows(ROOT / ".github" / "free-model-factories.tsv")
    lock = ROSTER.load_roster_lock(ROOT / ".github" / "factory-expected-workers.json")
    assert set(lock["expected_workers"]) == ROSTER.roster_worker_ids(rows)
    assert {40, 43, 44}.issubset(set(lock["retired_workers"]))


def test_catalog_miss_retires_opencode_pin() -> None:
    """A pin missing from ``opencode models opencode`` is retired."""
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "catalog-miss.json")
    rows = [
        _row("41", "opencode-free", "mimo-v2.5-free"),
        _row("39", "opencode-free", "big-pickle"),
        _row("46", "kilo-auto", "kilo-auto/free"),
    ]

    plan = RETIRE.plan_retirement(rows, catalogs)

    retired = {item.model: item for item in plan.retirements}
    assert "mimo-v2.5-free" in retired
    assert "absent from opencode models opencode" in retired["mimo-v2.5-free"].reason
    kept = {item.model for item in plan.kept}
    assert "big-pickle" in kept
    assert "kilo-auto/free" in kept


def test_cost_zero_present_keeps_opencode_pin() -> None:
    """A free cost-0 model still listed by OpenCode stays on the roster."""
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "keep-present.json")
    rows = [
        _row("39", "opencode-free", "big-pickle"),
        _row("41", "opencode-free", "mimo-v2.5-free"),
        _row("47", "opencode-free", "muse-spark-1.2-contributor-free"),
    ]

    plan = RETIRE.plan_retirement(rows, catalogs)

    assert plan.retirements == ()
    assert {item.model for item in plan.kept} == {
        "big-pickle",
        "mimo-v2.5-free",
        "muse-spark-1.2-contributor-free",
    }


def test_paid_model_is_not_proposed_for_opencode_free() -> None:
    """Paid Zen models never enter the unused-free discovery report."""
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "keep-present.json")
    rows = [_row("39", "opencode-free", "big-pickle")]

    plan = RETIRE.plan_retirement(rows, catalogs)
    unused = {item.model for item in plan.unused_free}

    assert "deepseek-v4-flash" not in unused
    assert "deepseek-v4-flash" in plan.paid_rejected
    assert "ling-3.0-flash-fin-free" in unused
    assert "muse-spark-1.3-contributor-free" in unused
    assert RETIRE.classify_opencode_free_eligibility(
        "deepseek-v4-flash",
        catalogs["opencode"].get("deepseek-v4-flash"),
    ) is False


def test_nvidia_kept_when_opencode_lists_even_if_integrate_api_omits() -> None:
    """NVIDIA pins follow ``opencode models nvidia``, not integrate.api dumps."""
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "catalog-miss.json")
    payload = json.loads((FIXTURES / "catalog-miss.json").read_text(encoding="utf-8"))
    assert "stepfun-ai/step-3.7-flash" in payload["integrate_api_missing"]
    rows = [_row("9", "nvidia", "stepfun-ai/step-3.7-flash")]

    plan = RETIRE.plan_retirement(rows, catalogs)

    assert plan.retirements == ()
    assert plan.kept[0].model == "stepfun-ai/step-3.7-flash"
    assert "opencode models nvidia" in plan.kept[0].reason


def test_kilo_auto_and_big_pickle_stay_unless_catalog_absent() -> None:
    """kilo-auto is never catalog-retired; big-pickle stays while listed."""
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "catalog-miss.json")
    rows = [
        _row("46", "kilo-auto", "kilo-auto/free"),
        _row("39", "opencode-free", "big-pickle"),
    ]

    plan = RETIRE.plan_retirement(rows, catalogs)

    assert plan.retirements == ()
    by_model = {item.model: item for item in plan.kept}
    assert "not enumerated" in by_model["kilo-auto/free"].reason
    assert by_model["big-pickle"].action == "keep"


# Temporary IDs only. Never read the live TSV for clustered-retirement
# coverage: production pins such as 10/16/17/18/19/66/67/70 disappear after
# a real apply and must not be the only way this suite proves rebalance.
SYNTHETIC_RETIRE_WORKERS = tuple(str(worker) for worker in range(801, 809))
SYNTHETIC_KEEP_WORKERS = tuple(str(worker) for worker in range(901, 929))


def _plan_for_workers(
    rows: list[dict[str, str]],
    workers: set[str],
) -> RETIRE.RetirementPlan:
    """Build a retirement plan that drops the named workers only."""
    return RETIRE.RetirementPlan(
        retirements=tuple(
            RETIRE.PinDecision(
                worker=row["worker"],
                source=row["source"],
                model=row["model"],
                action="retire",
                reason="absent from opencode models nvidia",
            )
            for row in rows
            if row["worker"] in workers
        ),
        kept=(),
        unused_free=(),
        paid_rejected=(),
        catalog_sources={},
    )


def _clustered_retirement_rows() -> tuple[list[dict[str, str]], frozenset[str], frozenset[str]]:
    """Build a 36-slot roster where eight clustered pins unbalance minutes.

    Every dispatcher minute starts with three workers. Four minutes hold two
    synthetic retirees each; after those eight pins drop, those buckets have
    one worker while the other eight stay at three. Worker ids live in the
    800/900 range so the proof never depends on the live factory TSV.

    Returns:
        Roster rows, retire worker ids, and retire model ids.
    """
    clustered_minutes = ROSTER.SCHEDULE_MINUTES[:4]
    filled_minutes = ROSTER.SCHEDULE_MINUTES[4:]
    keep_iter = iter(SYNTHETIC_KEEP_WORKERS)
    retire_iter = iter(SYNTHETIC_RETIRE_WORKERS)
    rows: list[dict[str, str]] = []
    retire_workers: list[str] = []
    retire_models: list[str] = []

    for minute in clustered_minutes:
        keeper = next(keep_iter)
        rows.append(_row(keeper, "nvidia", f"synthetic/keep-{keeper}", minute=str(minute)))
        for _index in range(2):
            worker = next(retire_iter)
            retire_workers.append(worker)
            if int(worker) <= 805:
                model = f"synthetic/retire-{worker}"
                source = "nvidia"
            else:
                model = f"synthetic/retire-{worker}:free"
                source = "openrouter-free"
            retire_models.append(model)
            rows.append(_row(worker, source, model, minute=str(minute)))

    for minute in filled_minutes:
        for _index in range(3):
            keeper = next(keep_iter)
            rows.append(_row(keeper, "nvidia", f"synthetic/keep-{keeper}", minute=str(minute)))

    assert next(keep_iter, None) is None
    assert next(retire_iter, None) is None
    assert ROSTER.schedule_is_balanced(rows)
    live_ids = {
        str(worker)
        for worker in ROSTER.roster_worker_ids(
            ROSTER.load_roster_rows(ROOT / ".github" / "free-model-factories.tsv")
        )
    }
    assert set(SYNTHETIC_RETIRE_WORKERS).isdisjoint(live_ids)
    assert set(SYNTHETIC_KEEP_WORKERS).isdisjoint(live_ids)
    return rows, frozenset(retire_workers), frozenset(retire_models)


def _write_clustered_retirement_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, list[dict[str, str]], frozenset[str], frozenset[str]]:
    """Write a temporary roster, lock, and catalog for clustered retirement.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Roster path, lock path, catalog path, rows, retire workers, and
        retire models.
    """
    rows, retire_workers, retire_models = _clustered_retirement_rows()
    roster = tmp_path / "free-model-factories.tsv"
    lock_path = tmp_path / "factory-expected-workers.json"
    catalog = tmp_path / "catalog-clustered-miss.json"
    ROSTER.write_roster_rows(
        roster,
        rows,
        comments=("# worker\tsource\tmodel\tminute\tscheduler\tdisplay_name",),
    )
    ROSTER.sync_roster_lock(rows, lock_path=lock_path)
    keep_models = [
        {"id": row["model"]}
        for row in rows
        if row["worker"] not in retire_workers and row["source"] == "nvidia"
    ]
    catalog.write_text(
        json.dumps(
            {
                "source": "synthetic-clustered-retirement",
                "providers": {
                    "opencode": [
                        {"id": "big-pickle", "cost": {"input": 0, "output": 0}},
                    ],
                    "nvidia": keep_models,
                    "openrouter": [{"id": "synthetic/unrelated:free"}],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return roster, lock_path, catalog, rows, retire_workers, retire_models


def test_rebalance_keeps_minutes_when_already_balanced() -> None:
    """A roster that already satisfies ±1 is left on its current minutes."""
    rows = [
        _row(str(index + 1), "nvidia", f"model-{index}", minute=str(minute))
        for index, minute in enumerate(ROSTER.SCHEDULE_MINUTES)
    ]

    rebalanced = ROSTER.rebalance_schedule_minutes(rows)

    assert [row["minute"] for row in rebalanced] == [row["minute"] for row in rows]
    assert [row["worker"] for row in rebalanced] == [row["worker"] for row in rows]
    assert ROSTER.schedule_is_balanced(rebalanced)


def test_rebalance_spreads_clustered_minutes() -> None:
    """Workers stacked on one minute are spread across the dispatcher grid."""
    rows = [
        _row(str(index + 1), "nvidia", f"model-{index}", minute="0")
        for index in range(len(ROSTER.SCHEDULE_MINUTES))
    ]

    rebalanced = ROSTER.rebalance_schedule_minutes(rows)

    assert {row["worker"] for row in rebalanced} == {row["worker"] for row in rows}
    assert ROSTER.schedule_is_balanced(rebalanced)
    assert {row["minute"] for row in rebalanced} == {
        str(minute) for minute in ROSTER.SCHEDULE_MINUTES
    }


def test_apply_rebalances_minutes_after_clustered_pin_retirement() -> None:
    """Removing clustered pins from a temp roster must leave minutes ±1.

    Replaces the live-TSV eight-pin assertion that broke once those production
    workers were retired. The synthetic roster still has eight clustered pins
    so apply has real work, then remaining minutes stay within ±1.
    """
    rows, retire_workers, _retire_models = _clustered_retirement_rows()
    raw_remaining = [row for row in rows if row["worker"] not in retire_workers]
    assert not ROSTER.schedule_is_balanced(raw_remaining)
    raw_counts = ROSTER.schedule_counts(raw_remaining)
    assert max(raw_counts.values()) - min(raw_counts.values()) > 1

    plan = _plan_for_workers(rows, set(retire_workers))
    assert {item.worker for item in plan.retirements} == set(retire_workers)

    remaining = RETIRE.apply_plan(rows, plan)
    remaining_ids = {int(row["worker"]) for row in remaining}

    assert remaining_ids == ROSTER.roster_worker_ids(rows) - {
        int(worker) for worker in retire_workers
    }
    assert ROSTER.schedule_is_balanced(remaining)
    counts = ROSTER.schedule_counts(remaining)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert set(counts) == set(ROSTER.SCHEDULE_MINUTES)


def test_apply_cli_rewrites_balanced_minutes_and_lock(tmp_path: Path) -> None:
    """CLI apply retires clustered pins, rebalances minutes, and syncs the lock."""
    roster, lock_path, catalog, _rows, retire_workers, retire_models = (
        _write_clustered_retirement_fixture(tmp_path)
    )

    status = RETIRE.run(
        [
            "apply",
            "--roster",
            str(roster),
            "--lock",
            str(lock_path),
            "--catalog-json",
            str(catalog),
        ]
    )
    remaining = ROSTER.load_roster_rows(roster)
    lock = ROSTER.load_roster_lock(lock_path)

    assert status == 0
    assert {row["worker"] for row in remaining}.isdisjoint(retire_workers)
    assert ROSTER.schedule_is_balanced(remaining)
    assert set(lock["expected_workers"]) == ROSTER.roster_worker_ids(remaining)
    assert {int(worker) for worker in retire_workers}.issubset(set(lock["retired_workers"]))
    assert retire_models.issubset(set(lock["retired_models"]))


def test_apply_removes_dead_pins_and_syncs_expected_workers(tmp_path: Path) -> None:
    """Apply updates the TSV and generated expected-worker lock together."""
    roster = tmp_path / "free-model-factories.tsv"
    lock_path = tmp_path / "factory-expected-workers.json"
    roster.write_text(
        "\n".join(
            [
                "# worker\tsource\tmodel\tminute\tscheduler\tdisplay_name",
                "9\tnvidia\tstepfun-ai/step-3.7-flash\t5\tdispatcher\tStep",
                "39\topencode-free\tbig-pickle\t10\tdispatcher\tPickle",
                "41\topencode-free\tmimo-v2.5-free\t15\tdispatcher\tMiMo",
                "46\tkilo-auto\tkilo-auto/free\t40\tdispatcher\tKilo Auto Free · Forge",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    catalogs = CATALOG.load_catalog_fixture(FIXTURES / "catalog-miss.json")
    rows = ROSTER.load_roster_rows(roster)
    plan = RETIRE.plan_retirement(rows, catalogs)
    remaining = RETIRE.apply_plan(rows, plan)
    ROSTER.write_roster_rows(roster, remaining, ROSTER.load_roster_comments(roster))
    lock = ROSTER.sync_roster_lock(
        remaining,
        lock_path=lock_path,
        extra_retired_workers=(int(item.worker) for item in plan.retirements),
        extra_retired_models=(item.model for item in plan.retirements),
    )

    workers = {row["worker"] for row in ROSTER.load_roster_rows(roster)}
    assert workers == {"9", "39", "46"}
    assert 41 in lock["retired_workers"]
    assert "mimo-v2.5-free" in lock["retired_models"]
    assert set(lock["expected_workers"]) == {9, 39, 46}


def test_fixture_is_used_when_opencode_binary_is_missing() -> None:
    """CI injects a recorded catalog instead of calling a missing CLI."""
    catalogs = CATALOG.load_provider_catalogs(
        fixture_path=FIXTURES / "keep-present.json",
        require_cli=False,
        opencode_bin="/definitely/missing/opencode",
    )

    assert set(catalogs) == {"opencode", "nvidia", "openrouter"}
    assert catalogs["opencode"].source == "fixture"
    assert "big-pickle" in catalogs["opencode"].model_ids()


def test_verbose_cli_text_parses_cost_zero() -> None:
    """Verbose ``opencode models`` text attaches cost metadata to selectors."""
    text = "\n".join(
        [
            "opencode/big-pickle",
            "{",
            '  "id": "big-pickle",',
            '  "pricing": {"input": 0, "output": 0}',
            "}",
            "opencode/paid-frontier",
            "{",
            '  "id": "paid-frontier",',
            '  "cost": {"input": 2.5, "output": 2.5}',
            "}",
        ]
    )

    catalog = CATALOG.parse_opencode_models_text(text, "opencode")
    pickle = catalog.get("big-pickle")
    paid = catalog.get("paid-frontier")

    assert pickle is not None and pickle.cost_is_zero is True
    assert paid is not None and paid.cost_is_paid is True
    assert RETIRE.classify_opencode_free_eligibility("paid-frontier", paid) is False
    unnamed_free = CATALOG.CatalogEntry(
        "opencode",
        "zen-zero",
        cost_input=pickle.cost_input,
        cost_output=pickle.cost_output,
    )
    assert RETIRE.classify_opencode_free_eligibility("zen-zero", unnamed_free) is True


def test_cli_plan_fails_closed_without_catalog(tmp_path: Path) -> None:
    """A missing OpenCode catalog must not silently keep or drop pins."""
    roster = tmp_path / "roster.tsv"
    roster.write_text(
        "39\topencode-free\tbig-pickle\t5\tdispatcher\tPickle\n",
        encoding="utf-8",
    )

    status = RETIRE.run(
        [
            "plan",
            "--roster",
            str(roster),
            "--opencode-bin",
            "/definitely/missing/opencode",
        ]
    )

    assert status == 2
