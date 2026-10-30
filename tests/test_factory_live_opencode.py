"""OpenCode free models are selected from live catalog, not permanent worker pins."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
selector = importlib.import_module("factory_live_opencode")


def catalog(*entries: tuple[str, int, int]) -> str:
    return json.dumps(
        {
            "models": [
                {"id": model, "cost": {"input": inbound, "output": outbound}}
                for model, inbound, outbound in entries
            ],
        }
    )


def roster(tmp_path: Path) -> Path:
    file = tmp_path / "factory.tsv"
    file.write_text(
        "# worker\tsource\tmodel\tminute\tscheduler\tdisplay_name\n"
        "41\topencode-free\told-free\t5\tdispatcher\tOld\n"
        "42\topencode-free\tother-free\t10\tdispatcher\tOther\n"
        "50\tnvidia\tsome-model\t15\tdispatcher\tNVIDIA\n",
        encoding="utf-8",
    )
    return file


def test_big_pickle_is_one_pool_candidate_not_many_fixed_workers(tmp_path: Path) -> None:
    raw = catalog(("big-pickle", 0, 0), ("model-a-free", 0, 0))
    assert selector.free_models(raw) == ["big-pickle", "model-a-free"]
    assert selector.select_model(raw, 41, 0, roster(tmp_path))["model"] == "big-pickle"
    assert selector.select_model(raw, 42, 0, roster(tmp_path))["model"] == "model-a-free"


def test_new_catalog_models_rotate_without_roster_pr(tmp_path: Path) -> None:
    raw = catalog(
        ("big-pickle", 0, 0),
        ("beam-free", 0, 0),
        ("model-cost-only", 0, 0),
    )
    selected = {
        selector.select_model(raw, 41, turn, roster(tmp_path))["model"] for turn in range(3)
    }
    assert selected == set(selector.free_models(raw))


def test_paid_names_do_not_bypass_free_cost_policy() -> None:
    raw = catalog(
        ("premium-free", 0, 1),
        ("paid", 1, 1),
        ("eligible-by-cost", 0, 0),
        ("big-pickle", 0, 0),
    )
    assert selector.free_models(raw) == ["big-pickle", "eligible-by-cost"]


def test_empty_catalog_and_non_opencode_worker_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no provably free"):
        selector.select_model(catalog(("paid", 1, 1)), 41, 0, roster(tmp_path))
    with pytest.raises(ValueError, match="no OpenCode free slot"):
        selector.select_model(catalog(("big-pickle", 0, 0)), 50, 0, roster(tmp_path))


def attempt(model: str, updated: str, outcome: str = "model_unavailable") -> dict[str, object]:
    """Build the real trusted registry attempt shape, including its run identity."""
    return {
        "author_association": "OWNER",
        "body": (
            "<!-- factory-model-unavailable:v1 run=123 -->\n"
            f"Source: opencode-free\nModel: {model}\nAttempt outcome: {outcome}\n"
            f"Updated: {updated}\nRun: 123"
        ),
    }


def test_registry_cooldown_expires_and_is_scoped_to_model(tmp_path: Path) -> None:
    """A durable failure survives worker overwrites without suppressing other models."""
    comments = tmp_path / "comments.json"
    comments.write_text(json.dumps([[attempt("ll-alpha-free", "2026-10-17T07:00:05Z")]]))
    from datetime import UTC, datetime

    now = int(datetime(2026, 10, 17, 7, 0, 5, tzinfo=UTC).timestamp())
    raw = catalog(("ll-alpha-free", 0, 0), ("big-pickle", 0, 0), ("paid", 1, 1))
    selected = {
        selector.select_model(raw, 41, turn, roster(tmp_path), comments, now_epoch=now)["model"]
        for turn in range(4)
    }
    assert selected == {"big-pickle"}
    selected_after_expiry = {
        selector.select_model(
            raw,
            41,
            turn,
            roster(tmp_path),
            comments,
            now_epoch=now + selector.COOLDOWN_SECONDS,
        )["model"]
        for turn in range(4)
    }
    assert selected_after_expiry == {"big-pickle", "ll-alpha-free"}


def test_forged_malformed_stale_and_future_evidence_has_no_effect() -> None:
    """Only authenticated, well-formed, current registry attempts affect rotation."""
    from datetime import UTC, datetime

    now = int(datetime(2026, 10, 17, 7, 0, 5, tzinfo=UTC).timestamp())
    forged = attempt("forged-free", "2026-10-17T07:00:05Z")
    forged["author_association"] = "NONE"
    via_app = attempt("app-free", "2026-10-17T07:00:05Z")
    via_app["performed_via_github_app"] = {"slug": "untrusted-worker"}
    malformed = attempt("bad-free", "not-a-date")
    no_marker = attempt("no-marker-free", "2026-10-17T07:00:05Z")
    no_marker["body"] = str(no_marker["body"]).split("\n", 1)[1]
    no_run = attempt("no-run-free", "2026-10-17T07:00:05Z")
    no_run["body"] = str(no_run["body"]).rsplit("\n", 1)[0]
    assert (
        selector.unavailable_models(
            [
                forged,
                via_app,
                malformed,
                no_marker,
                no_run,
                attempt("old-free", "2026-10-16T07:00:05Z"),
                attempt("future-free", "2026-10-18T07:00:05Z"),
                attempt("environment-free", "2026-10-17T07:00:05Z", "environment_failure"),
                None,
                "bad record",
            ],
            now_epoch=now,
        )
        == set()
    )
    assert selector.unavailable_models({"unexpected": "shape"}, now_epoch=now) == set()


def test_all_candidates_unavailable_and_later_success(tmp_path: Path) -> None:
    """Exhaustion fails closed; a newer real success restores a temporary failure."""
    from datetime import UTC, datetime

    now = int(datetime(2026, 10, 17, 7, 0, 5, tzinfo=UTC).timestamp())
    comments = tmp_path / "comments.json"
    failure = attempt("big-pickle", "2026-10-17T07:00:05Z")
    comments.write_text(json.dumps([failure]))
    raw = catalog(("big-pickle", 0, 0), ("paid", 1, 1))
    with pytest.raises(ValueError, match="All 1 candidates"):
        selector.select_model(raw, 41, 0, roster(tmp_path), comments, now_epoch=now)
    comments.write_text(
        json.dumps([failure, attempt("big-pickle", "2026-10-17T07:00:06Z", "success")])
    )
    assert (
        selector.select_model(raw, 41, 0, roster(tmp_path), comments, now_epoch=now + 1)["model"]
        == "big-pickle"
    )


@pytest.mark.parametrize(
    "log,expected",
    [
        ("Error: Model unavailable: opencode/ll-alpha-free", True),
        ("Error: Model unavailable: opencode/another-free", False),
        ("HTTP 429 rate limit", False),
        ("timeout after 180 seconds", False),
        ("HTTP 402 budget exhausted", False),
        ("Error: service temporarily unavailable", False),
    ],
)
def test_exact_smoke_failure_classification(tmp_path: Path, log: str, expected: bool) -> None:
    """Quota, timeout, and other models cannot produce this model's cooldown."""
    target = tmp_path / "outcome"
    assert selector.record_smoke_failure(log, "opencode/ll-alpha-free", target) is expected
    assert target.exists() is expected
    if expected:
        assert (
            target.read_text() == "model_unavailable\tModel unavailable: opencode/ll-alpha-free\n"
        )


def test_cli_consults_registry_evidence(tmp_path: Path) -> None:
    """A real dispatch CLI call excludes the unavailable candidate from rotation."""
    import subprocess
    from datetime import UTC, datetime

    raw_catalog = tmp_path / "catalog.json"
    raw_catalog.write_text(catalog(("big-pickle", 0, 0), ("ll-alpha-free", 0, 0)))
    comments = tmp_path / "comments.json"
    comments.write_text(
        json.dumps(
            [
                attempt("ll-alpha-free", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            ]
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".github/scripts/factory_live_opencode.py"),
            "--catalog",
            str(raw_catalog),
            "--comments",
            str(comments),
            "--worker",
            "42",
            "--rotation",
            "0",
            "--roster",
            str(roster(tmp_path)),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["model"] == "big-pickle"


@pytest.mark.parametrize(
    "outcome",
    [
        "unknown_failure",
        "provider_failure",
        "provider_quota",
        "provider_throttle",
        "control_plane_failure",
        "environment_failure",
        "unconfigured",
    ],
)
def test_non_recovery_outcomes_do_not_clear_active_cooldown(outcome: str) -> None:
    """A later fallback-lane or infra report cannot erase unavailable-model evidence."""
    from datetime import UTC, datetime

    now = int(datetime(2026, 10, 17, 7, 0, 6, tzinfo=UTC).timestamp())
    failure = attempt("ll-alpha-free", "2026-10-17T07:00:05Z")
    later = attempt("ll-alpha-free", "2026-10-17T07:00:06Z", outcome)
    for records in ([failure, later], [later, failure]):
        assert selector.unavailable_models(records, now_epoch=now) == {"ll-alpha-free"}
        assert (
            selector.unavailable_models(
                records,
                now_epoch=now + selector.COOLDOWN_SECONDS,
            )
            == set()
        )
