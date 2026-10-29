#!/usr/bin/env python3
"""Pair cold Roll CPU measurements for baseline vs a pinned router fix.

Both variants run from the SAME temporary worktree and virtual environment.
Selected app files are swapped from pinned Git refs; new files can be absent
in the baseline. Profiling scripts are copied into the disposable worktree. Measurements are uninstrumented process
user+system CPU, not Vercel billing. No production database or API is accessed.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile

from scripts.profile_cold_invocation import _measure_unprofiled
from scripts.profile_local_traffic import local_token, safe_database_url

# Run as a module from the repository root so the scripts package imports:
# `uv run python -m scripts.compare_cold_router_cpu ...`
ROOT = Path(__file__).resolve().parents[1]

ROUTER_PATH = "app/router_mounts.py"
FIX_COMMIT = "e03b13f330fcf477f1a35b3e3caf9afbefee6195"
METRICS = (
    "startup_cpu_ms",
    "first_request_cpu_ms",
    "full_cold_cpu_ms",
    "first_request_wall_ms",
    "warm_cpu_per_request_ms",
)


def _git(*args: str, cwd: Path = ROOT) -> str:
    """Read repository data without networking or touching the current branch."""
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        check=True, timeout=45,
    )
    return result.stdout


def _blob_at(ref: str, path: str, cwd: Path = ROOT) -> str | None:
    """Read one pinned Git blob; new modules may be absent in the baseline.

    Existence is checked against the selected tree with ``git ls-tree``.
    Matching ``git show`` stderr text cannot distinguish a genuinely absent
    path from the "exists on disk, but not in <commit>" case that refuses
    valid comparisons of newly added app modules.
    """
    in_tree = _git("ls-tree", ref, "--", path, cwd=cwd).strip()
    if not in_tree:
        return None
    return _git("show", f"{ref}:{path}", cwd=cwd)


def pair_order(pair: int) -> tuple[str, str]:
    """Alternate experiment order to reduce cache/warmup bias."""
    return ("baseline", "fixed") if pair % 2 else ("fixed", "baseline")


def summarize(results: list[dict]) -> str:
    """Display each paired difference plus medians; positive savings mean faster."""
    by_variant = {
        variant: {r["pair"]: r for r in results if r["variant"] == variant}
        for variant in ("baseline", "fixed")
    }
    pairs = sorted(by_variant["baseline"])
    if not pairs or pairs != sorted(by_variant["fixed"]):
        raise ValueError("Both variants must have the same completed pairs")
    out = [
        "# Paired cold Roll CPU comparison",
        "",
        "Both variants ran in the same temporary worktree and Python environment.",
        "Only the selected source files were exchanged between runs.",
        "Startup + first-request CPU are measured without CPU instrumentation.",
        "Positive 'saved' values favor the fixed router. NOT Vercel billing.",
        "",
        "| Pair | Baseline total CPU | Fixed total CPU | Saved | Baseline first GET CPU | Fixed first GET CPU |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for pair in pairs:
        b = by_variant["baseline"][pair]
        f = by_variant["fixed"][pair]
        saved = b["full_cold_cpu_ms"] - f["full_cold_cpu_ms"]
        out.append(
            f"| {pair} | {b['full_cold_cpu_ms']:.2f} ms | {f['full_cold_cpu_ms']:.2f} ms "
            f"| {saved:+.2f} ms | {b['first_request_cpu_ms']:.2f} ms "
            f"| {f['first_request_cpu_ms']:.2f} ms |"
        )
    out.extend([
        "",
        "## Median measurements (ms)",
        "",
        "| Metric | Baseline | Fixed | Median paired CPU/wall saved |",
        "|---|---:|---:|---:|",
    ])
    for key in METRICS:
        before = [by_variant["baseline"][p][key] for p in pairs]
        after = [by_variant["fixed"][p][key] for p in pairs]
        savings = [b - a for b, a in zip(before, after, strict=True)]
        out.append(
            f"| {key} | {statistics.median(before):.2f} "
            f"| {statistics.median(after):.2f} "
            f"| {statistics.median(savings):+.2f} |"
        )
    out.extend([
        "",
        "## Interpretation limits",
        "",
        "- This is local macOS process CPU, not Vercel Active CPU billing.",
        "- One-worker Python under loopback PostgreSQL, with synthetic fixture data.",
        "- Small sample counts cannot predict production scheduling or cold-start frequency.",
        "- All samples use a fresh Uvicorn process and the SAME repository path.",
    ])
    return "\n".join(out) + "\n"


def worker_command(
    output: Path, variant: str, pair: int, warm_requests: int
) -> list[str]:
    """Build the child worker command without any database URL argument.

    The password-bearing URL travels only in the child's environment, so
    other local users cannot read it from the process argument list.
    """
    return [
        sys.executable, "-m", "scripts.compare_cold_router_cpu",
        "--worker", "--variant", variant, "--pair", str(pair),
        "--warm-requests", str(warm_requests), "--output", str(output),
    ]


def run_worker(args: argparse.Namespace) -> int:
    """Measure one variant in a clean Python process in the temporary worktree."""
    # The database URL arrives via the environment, never the command line.
    db_url = os.environ.get("LOCAL_PROFILE_DATABASE_URL", "")
    safe_database_url(db_url)
    token = os.environ.get("LOCAL_PROFILE_ACCESS_TOKEN", "")
    if not token or not os.environ.get("SECRET_KEY"):
        raise RuntimeError("Local ephemeral token and signing key were not supplied")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = _measure_unprofiled(
        db_url, token, "/api/v2/roll/bootstrap", output,
        args.pair, args.warm_requests,
    )
    print(json.dumps({"variant": args.variant, "pair": args.pair, **result}))
    return 0


def compare(args: argparse.Namespace) -> int:
    """Alternate a pinned router fix against the original in one worktree."""
    safe_database_url(args.db_url)
    if not 2 <= args.pairs <= 10:
        raise ValueError("Use 2 to 10 paired runs")
    if not 1 <= args.warm_requests <= 20:
        raise ValueError("Use 1 to 20 warm requests per run")
    password = os.getenv("LOCAL_PROFILE_PASSWORD")
    if not password:
        raise ValueError("Set LOCAL_PROFILE_PASSWORD for the disposable test user")
    paths = tuple(args.changed_paths)
    if not paths or len(paths) != len(set(paths)):
        raise ValueError("Provide a unique nonempty set of source files")
    for path in paths:
        if not path.startswith("app/") or path.startswith("app/../") or ".." in Path(path).parts:
            raise ValueError(f"Only app/ source files may be compared: {path}")
    blobs = {
        variant: {path: _blob_at(ref, path) for path in paths}
        for variant, ref in (("baseline", args.baseline_ref), ("fixed", args.fixed_ref))
    }
    if blobs["baseline"] == blobs["fixed"]:
        raise RuntimeError("Selected files are identical; not an A/B test")

    os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
    output = (ROOT / ".profile-local" / (
        "cold-ab-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )).resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)

    print("Authenticating against disposable loopback database...", flush=True)
    token = local_token(args.db_url, output, args.username, password)
    environment = dict(
        os.environ,
        LOCAL_PROFILE_ACCESS_TOKEN=token,
        # Keep the password-bearing URL out of the worker's visible argv.
        LOCAL_PROFILE_DATABASE_URL=args.db_url,
    )
    results: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="comicpile-cold-ab-") as tmp:
        checkout = Path(tmp) / "checkout"
        _git("worktree", "add", "--detach", str(checkout), args.baseline_ref)
        try:
            # The profiling branch may not have been merged into the candidate
            # branch yet. Copy only the local test harness into the worktree.
            for script in (
                "profile_local_traffic.py",
                "profile_cold_invocation.py",
                "compare_cold_router_cpu.py",
            ):
                shutil.copy2(ROOT / "scripts" / script, checkout / "scripts" / script)
            for pair in range(1, args.pairs + 1):
                for variant in pair_order(pair):
                    for path in paths:
                        target = checkout / path
                        blob = blobs[variant][path]
                        if blob is None:
                            target.unlink(missing_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_text(blob, encoding="utf-8")
                    # CPU is measured in a fresh API subprocess in the worker;
                    # parent or worker startup overhead is excluded.
                    child_output = checkout / ".profile-local" / f"{pair}-{variant}"
                    child = subprocess.run(
                        worker_command(child_output, variant, pair, args.warm_requests),
                        cwd=checkout, env=environment,
                        capture_output=True, text=True, timeout=180,
                        check=False,
                    )
                    if child.returncode != 0:
                        raise RuntimeError(
                            f"{variant} run {pair} failed:\n{child.stdout}\n{child.stderr}"
                        )
                    result = json.loads(child.stdout.strip())
                    if result["first_status"] != 200 or not result["first_cold_header"]:
                        raise RuntimeError("Worker did not measure a successful cold Roll")
                    results.append(result)
                    print(
                        f"Pair {pair}: {variant} total={result['full_cold_cpu_ms']:.2f}ms "
                        f"first={result['first_request_cpu_ms']:.2f}ms",
                        flush=True,
                    )
        finally:
            _git("worktree", "remove", "--force", str(checkout))

    report = summarize(results)
    for filename, data in [
        ("report.md", report),
        ("report.json", json.dumps({"baseline_ref": args.baseline_ref, "fixed_ref": args.fixed_ref, "changed_paths": list(paths), "measurements": results}, indent=2)),
    ]:
        p = output / filename
        p.write_text(data + ("" if data.endswith("\n") else "\n"), encoding="utf-8")
        os.chmod(p, 0o600)
    print(report, flush=True)
    print(f"Report: {output / 'report.md'}", flush=True)
    return 0


def main() -> int:
    """Read arguments and execute the paired experiment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=os.getenv("LOCAL_PROFILE_DATABASE_URL", ""))
    parser.add_argument("--username", default="testuser")
    parser.add_argument("--baseline-ref", default="HEAD")
    parser.add_argument("--fixed-ref", default=FIX_COMMIT)
    parser.add_argument("--changed-paths", nargs="+", default=[ROUTER_PATH])
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--warm-requests", type=int, default=5)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--variant", choices=["baseline", "fixed"])
    parser.add_argument("--pair", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path(".profile-local"))
    args = parser.parse_args()
    try:
        if args.worker:
            if args.variant is None or args.pair < 1:
                raise ValueError("Worker requires variant and pair")
            return run_worker(args)
        return compare(args)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"Paired cold CPU comparison failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
