#!/usr/bin/env python3
"""Profile the local Option E loader with SQLAlchemy cursor timing.

Read-only local DB. Cursor timings include driver/DB waiting, not full ORM
materialization. Do not treat the difference as pure ORM CPU.
"""
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.profile_local_traffic import safe_database_url


async def run():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=10)
    a = p.parse_args()
    if not 3 <= a.runs <= 30:
        raise SystemExit("runs must be between 3 and 30")
    url = os.environ["LOCAL_PROFILE_DATABASE_URL"]
    safe_database_url(url)
    parts = urlsplit(url.replace("+asyncpg", ""))
    if parts.hostname != "127.0.0.1" or parts.port != 55435:
        raise SystemExit("Only disposable loopback Postgres is allowed")
    os.environ.update(DATABASE_URL=url, TEST_DATABASE_URL=url,
                      ENVIRONMENT="production", TEST_ENVIRONMENT="false")
    from sqlalchemy import event, text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.repositories.reading_shadow_repository import load_shadow_inputs

    engine = create_async_engine(url, connect_args={"server_settings": {
        "default_transaction_read_only": "on"
    }})
    observed = []
    timings = []

    def before(conn, cursor, statement, parameters, context, executemany):
        context._local_cursor_started = time.perf_counter_ns()

    def after(conn, cursor, statement, parameters, context, executemany):
        started = getattr(context, "_local_cursor_started", None)
        if started is not None:
            timings.append((time.perf_counter_ns() - started) / 1e6)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    event.listen(engine.sync_engine, "after_cursor_execute", after)
    try:
        async with async_sessionmaker(engine)() as db:
            uid = (await db.execute(text("SELECT id FROM users WHERE username=:n"),
                                    {"n":"testuser"})).scalar_one()
        for i in range(a.runs):
            timings.clear()
            async with async_sessionmaker(engine)() as db:
                cpu_start = time.process_time_ns()
                wall_start = time.perf_counter_ns()
                data = await load_shadow_inputs(db, uid, include_legacy_diagnostics=False)
                cpu = (time.process_time_ns() - cpu_start) / 1e6
                wall = (time.perf_counter_ns() - wall_start) / 1e6
            if data.unresolved:
                raise RuntimeError("Unresolved snapshot references")
            cursor = sum(timings)
            observed.append((cpu, wall, cursor, len(timings)))
            print(f"Run {i+1}: CPU={cpu:.2f} ms, wall={wall:.2f} ms, "
                  f"cursor={cursor:.2f} ms, queries={len(timings)}, "
                  f"non-cursor wall={wall-cursor:.2f} ms", flush=True)
        med = lambda i: statistics.median(row[i] for row in observed)
        print(f"Medians: CPU={med(0):.2f} ms; wall={med(1):.2f} ms; "
              f"cursor={med(2):.2f} ms; queries={med(3):g}; "
              f"non-cursor wall={statistics.median(row[1]-row[2] for row in observed):.2f} ms")
        print("Cursor includes SQL execution, driver wait and initial fetching; "
              "non-cursor includes ORM construction, processing and other Python work.")
        print("The measurements are not a proof of pure DB time versus pure ORM time.")
        print(f"Snapshot: {len(data.threads)} threads, {len(data.issues)} issues, "
              f"{len(data.lists)} lists, {len(data.prerequisites)} prerequisites")
        print("Read-only local testuser; SQL text and credentials are not printed.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run())
