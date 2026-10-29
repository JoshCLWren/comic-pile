#!/usr/bin/env python3
"""Read-only Option E pipeline timing on the disposable local database.

Separates load_shadow_inputs SQL+ORM, DTO construction, cycle validation,
and pure evaluation. CPU is process user+system; wall includes PostgreSQL wait.
Runs repeated fresh AsyncSession transactions after interpreter initialization.
No data writes or schema changes.
"""
import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.profile_local_traffic import safe_database_url

def ms(t): return round(t*1000,3)
async def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--runs",type=int,default=10)
    a=p.parse_args()
    if not 5<=a.runs<=50: raise ValueError("runs must be 5..50")
    url=os.environ["LOCAL_PROFILE_DATABASE_URL"]
    safe_database_url(url)
    parsed=urlsplit(url.replace("+asyncpg",""))
    if parsed.hostname!="127.0.0.1" or parsed.port!=55435:
        raise ValueError("Disposable loopback database required")
    os.environ.update(DATABASE_URL=url,TEST_DATABASE_URL=url,
                      ENVIRONMENT="production",TEST_ENVIRONMENT="false")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from app.repositories.reading_shadow_repository import load_shadow_inputs
    from app.services.reading_list_evaluator import ReadingSnapshot,evaluate
    from app.services.reading_list_cycle_validator import validate_reading_constraints
    engine=create_async_engine(url, connect_args={"server_settings":{
        "default_transaction_read_only":"on"}})
    rows=[]
    try:
        async with async_sessionmaker(engine)() as db:
            uid=(await db.execute(text("SELECT id FROM users WHERE username=:name"),
                                  {"name":"testuser"})).scalar_one()
        for i in range(a.runs):
            async with async_sessionmaker(engine)() as db:
                measures={}
                def stamps(): return time.process_time(),time.perf_counter()
                def finish(label,start):
                    measures[label+"_cpu_ms"]=ms(time.process_time()-start[0])
                    measures[label+"_wall_ms"]=ms(time.perf_counter()-start[1])
                t=stamps()
                inp=await load_shadow_inputs(db,uid,include_legacy_diagnostics=False)
                finish("load",t)
                if inp.unresolved: raise ValueError("Unresolved reading references")
                t=stamps()
                snapshot=ReadingSnapshot(user_id=inp.user_id,threads=inp.threads,
                    issues=inp.issues,lists=inp.lists,prerequisites=inp.prerequisites,
                    excluded_issue_ids=inp.excluded_issue_ids)
                finish("construct",t)
                t=stamps()
                validate_reading_constraints(snapshot)
                finish("validate",t)
                t=stamps()
                result=evaluate(snapshot)
                finish("evaluate",t)
                rows.append(measures)
                print(f"Run {i+1}: load CPU {measures['load_cpu_ms']:.3f} ms; "+
                      f"load wall {measures['load_wall_ms']:.3f} ms; "+
                      f"validate CPU {measures['validate_cpu_ms']:.3f} ms; "+
                      f"evaluate CPU {measures['evaluate_cpu_ms']:.3f} ms",flush=True)
        print("Medians (ms):")
        for name in ("load","construct","validate","evaluate"):
            print(f"  {name}: CPU={statistics.median(r[name+'_cpu_ms'] for r in rows):.3f}; "+
                  f"wall={statistics.median(r[name+'_wall_ms'] for r in rows):.3f}")
        print(f"Snapshot: {len(inp.threads)} threads, {len(inp.issues)} issues; "+
              f"{len(result)} active eligibility decisions")
        print("Read-only query sessions; no mutations. These warm per-stage times "+
              "are not full cold invocation CPU.")
    finally:
        await engine.dispose()

if __name__=="__main__":
    asyncio.run(main())
