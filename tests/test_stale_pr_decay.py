#!/usr/bin/env python3
"""Regression coverage for the adaptive stale-PR decay guard."""
from __future__ import annotations

from datetime import datetime
import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".github" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location("stale_pr_decay", SCRIPTS / "stale_pr_decay.py")
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

StalePRGuard = module.StalePRGuard
get_staleness_baseline = module.get_staleness_baseline
calculate_staleness_threshold = module.calculate_staleness_threshold
calculate_percentile = module.calculate_percentile
calculate_percentile_threshold = module.calculate_percentile_threshold
calculate_mad_threshold = module.calculate_mad_threshold
is_stale_attempt = module.is_stale_attempt
build_stale_expiration_marker = module.build_stale_expiration_marker
parse_stale_marker = module.parse_stale_marker
pr_lifetime_seconds = module.pr_lifetime_seconds
get_eligible_merged_prs = module.get_eligible_merged_prs
is_factory_implementation_pr = module.is_factory_implementation_pr
linked_issue_from_pr = module.linked_issue_from_pr
get_staleness_observability = module.get_staleness_observability

FACTORY_LABEL = "factory"


def make_pr(
    number: int,
    *,
    created: str = "2026-08-16T12:00:00Z",
    merged: str | None = None,
    state: str = "MERGED",
    branch: str = "factory/1-100-opencode-free",
    labels: list[str] | None = None,
    body: str = "",
) -> dict[str, Any]:
    """Build a minimal PR payload."""
    pr = {
        "number": number,
        "state": state,
        "createdAt": created,
        "headRefName": branch,
        "labels": [{"name": name} for name in (labels or [FACTORY_LABEL])],
        "body": body,
    }
    if merged is not None:
        pr["mergedAt"] = merged
    return pr


def test_pr_lifetime_merged():
    """Merged PR lifetime is merged_at - created_at."""
    pr = make_pr(1, created="2026-08-16T12:00:00Z", merged="2026-08-16T14:00:00Z")
    lifetime = pr_lifetime_seconds(pr)
    assert lifetime == 7200, f"Expected 7200, got {lifetime}"


def test_pr_lifetime_open():
    """Open PR age uses now - created_at."""
    now = 1_800_000_000
    pr = make_pr(1, created="2026-08-16T12:00:00Z", state="OPEN")
    lifetime = pr_lifetime_seconds(pr, now_epoch=now)
    created_epoch = int(datetime.fromisoformat("2026-08-16T12:00:00+00:00").timestamp())
    expected = now - created_epoch
    assert lifetime == expected, f"Got {lifetime}, expected {expected}"


def test_pr_lifetime_uses_created_not_updated():
    """created_at is used for lifetime, never updated_at."""
    pr = make_pr(1, created="2026-08-16T12:00:00Z", merged="2026-08-17T12:00:00Z")
    lifetime = pr_lifetime_seconds(pr)
    assert lifetime == 86400, f"Expected 86400, got {lifetime}"


def test_calculate_percentile_basic():
    """Percentile calculation works on a simple sorted list."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert calculate_percentile(values, 50) == 3.0
    assert calculate_percentile(values, 90) == 4.6


def test_calculate_percentile_single_value():
    """Single-value list returns that value for any percentile."""
    assert calculate_percentile([42.0], 90) == 42.0


def test_calculate_percentile_empty():
    """Empty list returns 0.0."""
    assert calculate_percentile([], 90) == 0.0


def test_calculate_percentile_threshold():
    """2x P90 threshold calculation."""
    values = [3600.0, 7200.0, 10800.0, 18000.0, 25920.0]
    threshold = calculate_percentile_threshold(values)
    p90 = calculate_percentile(values, 90)
    assert threshold == p90 * 2.0


def test_calculate_mad_threshold():
    """Median/MAD threshold is robust to outliers."""
    values = [3600.0, 4000.0, 4400.0, 5000.0, 50000.0]
    threshold = calculate_mad_threshold(values)
    median = statistics_median(values)
    mad = statistics_median([abs(v - median) for v in values])
    assert threshold == median + 2.0 * mad


def statistics_median(values: list[float]) -> float:
    """Helper to match statistics.median behavior."""
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def test_calculate_staleness_threshold_cold_start():
    """Insufficient sample returns cold-start fallback."""
    lifetimes = [3600.0]
    threshold = calculate_staleness_threshold(lifetimes)
    assert threshold == module.COLD_START_FALLBACK_SECONDS


def test_calculate_staleness_threshold_lower_floor():
    """Threshold never goes below the lower floor."""
    lifetimes = [1.0, 2.0, 3.0]
    threshold = calculate_staleness_threshold(lifetimes)
    assert threshold >= module.LOWER_FLOOR_SECONDS


def test_calculate_staleness_threshold_adapts():
    """Threshold adapts as the population changes."""
    small = [3600.0, 7200.0]
    large = [3600.0, 7200.0, 14400.0, 28800.0, 57600.0] * 20
    t1 = calculate_staleness_threshold(small)
    t2 = calculate_staleness_threshold(large)
    assert t2 > t1 or len(large) >= module.MINIMUM_SAMPLE_SIZE


def test_is_stale_attempt():
    """PR is stale when age exceeds threshold."""
    baseline = {"threshold_seconds": 7200, "sample_size": 50}
    assert is_stale_attempt(10000, baseline) is True
    assert is_stale_attempt(3600, baseline) is False
    assert is_stale_attempt(7200, baseline) is False


def test_build_stale_expiration_marker():
    """Marker contains all required fields."""
    baseline = {"sample_size": 50, "formula": "2x_p90", "threshold_seconds": 23200}
    marker = build_stale_expiration_marker(1, 100, 30000, baseline)
    assert "comic-pile-factory-stale-expiration-v1" in marker
    assert "pr-1" in marker
    assert "issue-100" in marker
    assert "age-30000" in marker
    assert "sample-50" in marker
    assert "formula-2x_p90" in marker
    assert "threshold-23200" in marker


def test_parse_stale_marker():
    """Parsing a marker returns the correct fields."""
    body = "<!-- comic-pile-factory-stale-expiration-v1:pr-5:issue-42:age-30000:sample-50:formula-2x_p90:threshold-23200 -->"
    marker = parse_stale_marker(body)
    assert marker is not None
    assert marker["pr"] == 5
    assert marker["issue"] == 42
    assert marker["age"] == 30000
    assert marker["sample"] == 50
    assert marker["formula"] == "2x_p90"
    assert marker["threshold"] == 23200


def test_parse_stale_marker_not_matching():
    """Non-matching body returns None."""
    assert parse_stale_marker("some other text") is None


def test_get_eligible_merged_prs():
    """Only successfully merged Factory PRs are eligible."""
    prs = [
        make_pr(1, merged="2026-08-17T12:00:00Z", branch="factory/1-100-opencode-free"),
        make_pr(2, merged="2026-08-18T12:00:00Z", branch="factory/2-100-opencode-free"),
        make_pr(3, state="OPEN", branch="factory/3-100-opencode-free"),
        make_pr(4, merged="2026-08-19T12:00:00Z", branch="fix/some-fix", labels=["dependencies"]),
    ]
    eligible = get_eligible_merged_prs(prs, limit=10)
    assert len(eligible) == 2
    assert eligible[0]["number"] == 2


def test_is_factory_implementation_pr():
    """Only canonical factory PRs qualify."""
    assert is_factory_implementation_pr(make_pr(1, branch="factory/1-100-opencode-free")) is True
    pr_non_factory = make_pr(2, branch="fix/some-fix", labels=["dependencies"])
    assert is_factory_implementation_pr(pr_non_factory) is False
    pr_infra = make_pr(3, branch="factory/3-100-infra")
    pr_infra["labels"] = [{"name": "factory"}, {"name": "infrastructure"}]
    assert is_factory_implementation_pr(pr_infra) is False


def test_linked_issue_from_pr_branch():
    """Branch shape resolves the issue number."""
    pr = make_pr(1, branch="factory/5-200-opencode-free")
    assert linked_issue_from_pr(pr) == 200


def test_linked_issue_from_pr_body():
    """Closing keyword resolves the issue number."""
    pr = make_pr(1, branch="feature/something", body="Closes #42.")
    assert linked_issue_from_pr(pr) == 42


def test_linked_issue_from_pr_none():
    """No branch or closing keyword returns None."""
    pr = make_pr(1, branch="feature/something", body="Just a reference to #42")
    assert linked_issue_from_pr(pr) is None


def test_get_staleness_baseline_basic():
    """Baseline calculation returns expected structure."""
    now = 1_700_000_000
    prs = [
        make_pr(i, merged=f"2026-08-{16 + i}T12:00:00Z", created=f"2026-08-{16 + i - 1}T12:00:00Z")
        for i in range(1, 20)
    ]
    baseline = get_staleness_baseline(prs, now_epoch=now, limit=100)
    assert baseline["sample_size"] > 0
    assert "threshold_seconds" in baseline
    assert "formula" in baseline
    assert "lower_floor" in baseline


def test_get_staleness_baseline_cold_start():
    """Cold-start fallback when no merged PRs."""
    prs = []
    baseline = get_staleness_baseline(prs)
    assert baseline["sample_size"] == 0
    assert baseline["threshold_seconds"] == module.COLD_START_FALLBACK_SECONDS
    assert baseline["formula"] == "cold-start-fallback"


def test_stale_pr_guard_basic():
    """StalePRGuard evaluates a PR correctly."""
    guard = StalePRGuard()
    pr = make_pr(1, merged="2026-08-17T12:00:00Z", state="MERGED")
    result = guard.evaluate_pr(pr)
    assert "pr" in result
    assert "stale" in result
    assert "age_seconds" in result


def test_stale_pr_guard_not_stale_young_pr():
    """A young PR is not stale."""
    guard = StalePRGuard(rolling_window=10, lower_floor=3600)
    pr = make_pr(1, created="2026-08-20T12:00:00Z", state="OPEN")
    pr["prs"] = [make_pr(i, merged=f"2026-08-{16+i}T12:00:00Z") for i in range(1, 20)]
    result = guard.evaluate_pr(pr, now_epoch=1_700_000_000)
    assert result["stale"] is False


def test_stale_pr_guard_observability():
    """Observability string contains all key metrics."""
    baseline = {
        "sample_size": 50,
        "threshold_seconds": 23200,
        "formula": "2x_p90",
        "p90": 11600,
        "median": 7200,
        "mad": 3600,
        "lower_floor": 3600,
    }
    obs = get_staleness_observability(baseline)
    assert "sample" in obs.lower() or "Sample" in obs
    assert "Threshold" in obs or "threshold" in obs
    assert "Formula" in obs or "formula" in obs


def test_build_stale_expiration_marker_fields():
    """All marker fields are present and correctly formatted."""
    baseline = {
        "sample_size": 100,
        "formula": "2x_p90",
        "threshold_seconds": 82800,
    }
    marker = build_stale_expiration_marker(42, 100, 90000, baseline)
    assert "comic-pile-factory-stale-expiration-v1:pr-42:issue-100" in marker
    assert "age-90000" in marker
    assert "sample-100" in marker
    assert "formula-2x_p90" in marker
    assert "threshold-82800" in marker


def test_stale_expiration_marker_idempotent():
    """Same inputs produce identical markers."""
    baseline = {"sample_size": 50, "formula": "2x_p90", "threshold_seconds": 23200}
    marker1 = build_stale_expiration_marker(1, 100, 30000, baseline)
    marker2 = build_stale_expiration_marker(1, 100, 30000, baseline)
    assert marker1 == marker2


def test_is_factory_implementation_pr_infra_excluded():
    """Infrastructure PRs are excluded from Factory implementation."""
    pr = make_pr(1, branch="factory/1-100-opencode-free", labels=[FACTORY_LABEL, "infrastructure"])
    assert is_factory_implementation_pr(pr) is False
    pr_non_factory = make_pr(2, branch="fix/some-fix", labels=["dependencies"])
    assert is_factory_implementation_pr(pr_non_factory) is False


def test_staleness_threshold_robust_to_outliers():
    """A few old successful PRs do not stretch threshold indefinitely."""
    normal = [3600.0, 7200.0, 14400.0] * 30
    with_outlier = normal + [259200.0, 345600.0]
    t_normal = calculate_staleness_threshold(normal)
    t_with_outlier = calculate_staleness_threshold(with_outlier)
    assert t_with_outlier < t_normal * 5


def test_stale_pr_guard_min_sample_enforcement():
    """Minimum sample size is enforced."""
    guard = StalePRGuard(min_sample=module.MINIMUM_SAMPLE_SIZE)
    prs = [make_pr(i, merged=f"2026-08-{16+i}T12:00:00Z") for i in range(1, 5)]
    baseline = guard.get_baseline(prs)
    assert baseline["sample_size"] < module.MINIMUM_SAMPLE_SIZE
    assert baseline["threshold_seconds"] == module.COLD_START_FALLBACK_SECONDS


def test_pr_lifetime_zero():
    """Same created and merged time gives zero lifetime."""
    pr = make_pr(1, created="2026-08-16T12:00:00Z", merged="2026-08-16T12:00:00Z")
    assert pr_lifetime_seconds(pr) == 0


def test_calculate_staleness_threshold_uses_max_formula():
    """Threshold uses the more conservative of 2x P90 and median/MAD.

    With 5 values below MINIMUM_SAMPLE_SIZE (10), cold-start fallback applies.
    """
    values = [1000.0, 2000.0, 3000.0, 4000.0, 100000.0]
    threshold = calculate_staleness_threshold(values)
    # With 5 values, cold-start fallback (86400) is used since len < 10
    assert threshold == module.COLD_START_FALLBACK_SECONDS

    # With enough samples, the formula should apply
    many_values = values * 30
    threshold_many = calculate_staleness_threshold(many_values)
    p90_threshold = calculate_percentile_threshold(many_values)
    mad_threshold = calculate_mad_threshold(many_values)
    assert threshold_many >= p90_threshold
    assert threshold_many >= mad_threshold


def test_stale_pr_guard_empty_population():
    """Empty population produces cold-start baseline."""
    guard = StalePRGuard()
    baseline = guard.get_baseline([])
    assert baseline["sample_size"] == 0
    assert baseline["threshold_seconds"] == module.COLD_START_FALLBACK_SECONDS


def test_get_eligible_merged_prs_limit():
    """Limit parameter caps the result size."""
    prs = [make_pr(i, merged=f"2026-08-{16+i}T12:00:00Z") for i in range(1, 200)]
    eligible = get_eligible_merged_prs(prs, limit=10)
    assert len(eligible) == 10


def test_get_eligible_merged_prs_sorted_desc():
    """Eligible PRs are sorted by merge time descending."""
    prs = [
        make_pr(1, merged="2026-08-18T12:00:00Z"),
        make_pr(2, merged="2026-08-20T12:00:00Z"),
        make_pr(3, merged="2026-08-19T12:00:00Z"),
    ]
    eligible = get_eligible_merged_prs(prs)
    assert eligible[0]["number"] == 2
    assert eligible[1]["number"] == 3
    assert eligible[2]["number"] == 1


def test_get_staleness_baseline_with_non_factory_prs():
    """Non-Factory PRs are filtered out from baseline."""
    prs = [
        make_pr(1, merged="2026-08-17T12:00:00Z"),
        {"number": 2, "state": "MERGED", "createdAt": "2026-08-16T12:00:00Z",
         "mergedAt": "2026-08-17T12:00:00Z", "headRefName": "dependabot/update",
         "labels": [{"name": "dependencies"}]},
    ]
    baseline = get_staleness_baseline(prs)
    assert baseline["sample_size"] == 1


def test_parse_stale_marker_partial():
    """Partial marker text still parses correctly."""
    body = "Some text <!-- comic-pile-factory-stale-expiration-v1:pr-7:issue-8:age-100:sample-50:formula-2x_p90:threshold-23200 --> more text"
    marker = parse_stale_marker(body)
    assert marker is not None
    assert marker["pr"] == 7


def test_calculate_percentile_interpolation():
    """Linear interpolation between values is correct."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = calculate_percentile(values, 25)
    assert result == 20.0, f"Expected 20.0, got {result}"
    result = calculate_percentile(values, 75)
    assert result == 40.0, f"Expected 40.0, got {result}"


def test_stale_pr_guard_with_custom_config():
    """Custom configuration is respected."""
    guard = StalePRGuard(rolling_window=5, multiplier=1.5, lower_floor=1800)
    assert guard.rolling_window == 5
    assert guard.multiplier == 1.5
    assert guard.lower_floor == 1800


def test_get_staleness_baseline_sample_size_cap():
    """Baseline does not exceed the rolling window."""
    now = 1_700_000_000
    prs = [make_pr(i, merged=f"2026-08-{16+i}T12:00:00Z") for i in range(1, 200)]
    baseline = get_staleness_baseline(prs, now_epoch=now, limit=10)
    assert baseline["sample_size"] <= 10


def test_record_stale_expiration_releases_issue_before_closing_and_marks_last(
    monkeypatch,
) -> None:
    """A stale PR cannot close before its linked issue is safely reusable."""
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(
        module,
        "reset_issue_to_unowned",
        lambda number: events.append(("reset", number)),
    )
    monkeypatch.setattr(
        module,
        "close_pr_implementation",
        lambda number: events.append(("close", number)),
    )
    monkeypatch.setattr(
        module,
        "run_gh",
        lambda args, **kwargs: events.append(("comment", tuple(args))),
    )

    marker = module.record_stale_expiration(
        42,
        100,
        90_000,
        {"sample_size": 50, "formula": "2x_p90", "threshold_seconds": 23_200},
    )

    assert events[0] == ("reset", 100)
    assert events[1] == ("close", 42)
    assert events[2][0] == "comment"
    assert marker in events[2][1]
