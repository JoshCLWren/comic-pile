#!/usr/bin/env python3
"""CPU-profile a complete local API cold invocation without elevated privileges.

Run with the production-path loopback environment supplied by
profile_cold_invocation.py. cProfile starts BEFORE importing Uvicorn/FastAPI
and writes the call graph when the server stops after the first request.

The profiler's own overhead inflates timings. Compare only the separate,
unprofiled process CPU measurements to estimate cold-start costs.
"""

from __future__ import annotations

import argparse
import cProfile
import os
from pathlib import Path
import pstats
import time


def save_profile(profile: cProfile.Profile, output: Path) -> tuple[Path, Path]:
    """Save the complete CPU-timed call graph plus readable hot-function tables."""
    output.parent.mkdir(parents=True, exist_ok=True)
    profile.disable()
    profile.dump_stats(str(output))
    os.chmod(output, 0o600)
    report_path = output.with_suffix(".top.txt")
    with report_path.open("w", encoding="utf-8") as report:
        report.write("cProfile with time.process_time() timer (Python process CPU).\n")
        report.write("Cumulative and self time include profiler overhead.\n\n")
        stats = pstats.Stats(profile, stream=report)
        report.write("=== Top 50 functions by SELF CPU ===\n")
        stats.sort_stats(pstats.SortKey.TIME).print_stats(50)
        report.write("\n=== Top 50 functions by CUMULATIVE CPU ===\n")
        stats.sort_stats(pstats.SortKey.CUMULATIVE).print_stats(50)
    os.chmod(report_path, 0o600)
    return output, report_path


def main() -> int:
    """Run Uvicorn once, save the CPU call graph even on graceful interruption."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if not args.output.is_absolute():
        parser.error("output must be an absolute local file path")

    profile = cProfile.Profile(timer=time.process_time)
    profile.enable()
    try:
        # Import inside the profiler to capture the expensive import graph.
        import uvicorn

        uvicorn.run(
            "api.index:app",
            host="127.0.0.1",
            port=args.port,
            workers=1,
            access_log=False,
        )
    except KeyboardInterrupt:
        # SIGINT before Uvicorn installs its handlers also needs to save stats.
        pass
    finally:
        save_profile(profile, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
