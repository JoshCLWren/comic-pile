#!/usr/bin/env python3
"""Read-only parity against existing LOCAL testuser Option E snapshot.

Loads real disposable database inputs via production loader, compares complete
canonical Python evaluator results to native Rust. No writes, exports, or logging
of issue titles, tokens, database URLs, or other user data.
"""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from dataclasses import asdict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.profile_local_traffic import safe_database_url

BIN = Path(__file__).resolve().parent / "target/release/eligibility"

async def run():
    raw = os.environ["LOCAL_PROFILE_DATABASE_URL"]
    safe_database_url(raw)
    parsed = urlsplit(raw.replace("+asyncpg", ""))
    if parsed.hostname != "127.0.0.1" or parsed.port != 55435:
        raise ValueError("Only disposable loopback database accepted")
    if not BIN.is_file():
        raise RuntimeError("Compile release eligibility binary first")

    # Import after validating local configuration.
    os.environ["DATABASE_URL"] = raw
    os.environ["TEST_DATABASE_URL"] = raw
    os.environ["TEST_ENVIRONMENT"] = "false"
    os.environ["ENVIRONMENT"] = "production"
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_list_evaluator import ReadingSnapshot, evaluate
    from app.services.reading_list_cycle_validator import validate_reading_constraints

    engine = create_async_engine(raw, connect_args={"server_settings": {
        "default_transaction_read_only": "on"
    }})
    try:
        async with async_sessionmaker(engine)() as session:
            user_id = (await session.execute(text(
                "SELECT id FROM users WHERE username = :name"
            ), {"name": "testuser"})).scalar_one()
            inputs = await load_shadow_inputs(
                session, user_id, include_legacy_diagnostics=False
            )
            if inputs.unresolved:
                raise ValueError("Unresolved reading references: refusing comparison")
            snapshot = ReadingSnapshot(
                user_id=inputs.user_id,
                threads=inputs.threads,
                issues=inputs.issues,
                lists=inputs.lists,
                prerequisites=inputs.prerequisites,
                excluded_issue_ids=inputs.excluded_issue_ids
            )
            validate_reading_constraints(snapshot)
            py = [
                {"thread_id": k, "next_issue_id": v.next_issue_id,
                 "eligible": v.eligible, "blockers": [asdict(b) for b in v.blockers]}
                for k,v in evaluate(snapshot).items()
            ]
            payload = asdict(snapshot)
            payload["excluded_issue_ids"] = sorted(snapshot.excluded_issue_ids)
            result = subprocess.run(
                [str(BIN)], input=json.dumps(payload), capture_output=True,
                text=True, check=True, timeout=20
            )
            rust = json.loads(result.stdout)
            py = json.loads(json.dumps(py))
            if rust != py:
                py_by_id = {row["thread_id"]: row for row in py}
                rs_by_id = {row["thread_id"]: row for row in rust}
                mismatch = [k for k in py_by_id.keys() | rs_by_id.keys()
                            if py_by_id.get(k) != rs_by_id.get(k)]
                print(f"FAIL: {len(mismatch)} divergent threads (identities withheld)")
                raise AssertionError("Native vs canonical Option E mismatch")
            print("PASS: native Rust matches canonical Python on existing testuser data")
            print(f"Threads: {len(inputs.threads)}; issues: {len(inputs.issues)}; "
                  f"lists: {len(inputs.lists)}; prerequisites: {len(inputs.prerequisites)}")
            print(f"Active thread results: {len(py)}; "
                  f"eligible: {sum(row['eligible'] for row in py)}")
            print("Read-only transaction; no database mutations")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
