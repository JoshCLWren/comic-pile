#!/usr/bin/env python3
"""Trusted Neon decision projections for the ComicPile factory.

Only trusted Actions controllers use these functions. Agent/model runner jobs
must never receive FACTORY_STATE_DSN_FILE. GitHub remains authoritative for
review, code, exact-head checks, labels, and merges. SQL projections are hints
and capacity reservations, never merge authorization.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from factory_state_cache import _dsn

SCHEMA = [
  "CREATE TABLE IF NOT EXISTS public.factory_model_health (\n repo text NOT NULL, source text NOT NULL, model text NOT NULL,\n status text NOT NULL DEFAULT 'unknown', last_outcome text,\n cooldown_until timestamptz, last_verified_at timestamptz,\n last_run_id bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now(),\n PRIMARY KEY (repo,source,model))",
  "CREATE TABLE IF NOT EXISTS public.factory_provider_budget (\n repo text NOT NULL, source text NOT NULL,\n cooldown_until timestamptz, quota_reset_at timestamptz,\n concurrency_limit integer, daily_limit integer,\n usage_day date NOT NULL DEFAULT (now() AT TIME ZONE 'UTC')::date,\n daily_used integer NOT NULL DEFAULT 0, last_run_id bigint NOT NULL DEFAULT 0, last_outcome text,\n updated_at timestamptz NOT NULL DEFAULT now(),\n PRIMARY KEY (repo,source),\n CONSTRAINT factory_provider_capacity_nonnegative CHECK (concurrency_limit IS NULL OR concurrency_limit > 0),\n CONSTRAINT factory_provider_daily_nonnegative CHECK (daily_limit IS NULL OR daily_limit >= 0))",
  "CREATE TABLE IF NOT EXISTS public.factory_provider_reservation (\n claim_id uuid PRIMARY KEY, repo text NOT NULL, worker text NOT NULL,\n source text NOT NULL, expires_at timestamptz NOT NULL)",
  "CREATE INDEX IF NOT EXISTS idx_factory_provider_reservation_active ON public.factory_provider_reservation(repo,source,expires_at)",
  "CREATE TABLE IF NOT EXISTS public.factory_pr_stage_retry (\n repo text NOT NULL, pr_number bigint NOT NULL, head_sha text NOT NULL, stage text NOT NULL,\n attempts integer NOT NULL DEFAULT 0, outcome text NOT NULL,\n retry_after timestamptz, last_run_id bigint NOT NULL DEFAULT 0,\n updated_at timestamptz NOT NULL DEFAULT now(),\n PRIMARY KEY (repo,pr_number,head_sha,stage))",
  "CREATE TABLE IF NOT EXISTS public.factory_check_projection (\n repo text NOT NULL, pr_number bigint NOT NULL, head_sha text NOT NULL,\n check_name text NOT NULL, conclusion text NOT NULL, run_id bigint NOT NULL,\n observed_at timestamptz NOT NULL,\n PRIMARY KEY (repo,pr_number,head_sha,check_name))",
  "CREATE TABLE IF NOT EXISTS public.factory_worker_metrics (\n repo text NOT NULL, worker text NOT NULL, source text NOT NULL, model text NOT NULL,\n attempts bigint NOT NULL DEFAULT 0, productive bigint NOT NULL DEFAULT 0,\n completed bigint NOT NULL DEFAULT 0, failures bigint NOT NULL DEFAULT 0,\n last_run_id bigint NOT NULL DEFAULT 0, updated_at timestamptz NOT NULL DEFAULT now(),\n PRIMARY KEY (repo,worker,source,model))",
  "CREATE TABLE IF NOT EXISTS public.factory_runtime_event_keys (\n repo text NOT NULL, run_id bigint NOT NULL, PRIMARY KEY (repo,run_id))",
  "CREATE TABLE IF NOT EXISTS public.factory_reconciliation_cursor (\n repo text NOT NULL, scope text NOT NULL,\n checkpoint text, checked_at timestamptz NOT NULL DEFAULT now(),\n changed_count bigint NOT NULL DEFAULT 0,\n PRIMARY KEY (repo,scope))"
]

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
HEAD_RE = re.compile(r"^[a-f0-9]{40}$")
TRANSIENT = {"provider_failure": 900, "provider_throttle": 1800, "provider_quota": 1800}
MODEL_COOLDOWNS = {"model_unavailable": 21600, "model_policy_violation": 21600,
                   "model_retired_410": 21600}
# Independent OmniRoute routes do not share a provider-wide throttle.
MODEL_SCOPED_SOURCES = {"omniroute-free", "omniroute-opencode"}


def enabled() -> bool:
    return bool(os.environ.get("FACTORY_STATE_DSN_FILE"))


def _roster() -> dict[str, tuple[str, str]]:
    path = Path(__file__).resolve().parents[1] / "free-model-factories.tsv"
    result: dict[str, tuple[str, str]] = {}
    for row in path.read_text(encoding="utf-8").splitlines():
        fields = row.split("\t")
        if len(fields) >= 3 and fields[0].isdigit():
            result[fields[0]] = (fields[1], fields[2])
    return result


async def ensure_schema(conn: Any) -> None:
    # Zero destructive DDL. Reproducible on an empty factory_state database.
    if await conn.fetchval("SELECT to_regclass('public.factory_reconciliation_cursor')") is not None:
        return
    for statement in SCHEMA:
        await conn.execute(statement)


async def _connection() -> Any:
    import asyncpg
    return await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=15)


def _run(fn: Any, *args: Any) -> Any:
    async def call() -> Any:
        conn = await _connection()
        try:
            await ensure_schema(conn)
            return await fn(conn, *args)
        finally:
            await conn.close()
    return asyncio.run(call())


def _provider_cooldown(source: str, outcome: str, observed: datetime) -> datetime | None:
    if outcome not in TRANSIENT:
        return None
    if outcome == "provider_quota":
        try:
            from factory_quota_pause import quota_reset_epoch
            reset = quota_reset_epoch(source, int(observed.timestamp()))
            if reset > observed.timestamp():
                return datetime.fromtimestamp(reset, timezone.utc)
        except (ImportError, ValueError, KeyError):
            pass
    return observed + timedelta(seconds=TRANSIENT[outcome])


async def project_runtime(conn: Any, repo: str, run_id: int, outcome: dict[str, Any]) -> bool:
    """Idempotently update model, provider, retry and worker metrics projections."""
    worker = str(outcome.get("worker") or "")
    roster = _roster()
    if worker not in roster or not repo or not REPO_RE.fullmatch(repo):
        raise ValueError("untrusted worker or repository")
    source, configured_model = roster[worker]
    if str(outcome.get("source") or "") != source:
        raise ValueError("runtime source disagrees with the trusted roster")
    model = str(outcome.get("model") or configured_model)
    if not model or len(model) > 180:
        raise ValueError("invalid model")
    classification = str(outcome.get("outcome_class") or "unknown_failure")
    proven = outcome.get("exact_model_proven") is True
    persisted = outcome.get("persisted_work") is True
    observed = datetime.now(timezone.utc)
    async with conn.transaction():
        inserted = await conn.fetchval(
            """INSERT INTO public.factory_runtime_event_keys(repo,run_id)
               VALUES($1,$2) ON CONFLICT DO NOTHING RETURNING run_id""", repo, run_id)
        if inserted is None:
            return False
        await conn.execute(
            """INSERT INTO public.factory_worker_metrics
                 (repo,worker,source,model,attempts,productive,completed,failures,last_run_id)
               VALUES($1,$2,$3,$4,1,$5,$6,$7,$8)
               ON CONFLICT(repo,worker,source,model) DO UPDATE SET
                 attempts=factory_worker_metrics.attempts+1,
                 productive=factory_worker_metrics.productive+EXCLUDED.productive,
                 completed=factory_worker_metrics.completed+EXCLUDED.completed,
                 failures=factory_worker_metrics.failures+EXCLUDED.failures,
                 last_run_id=greatest(factory_worker_metrics.last_run_id,EXCLUDED.last_run_id),
                 updated_at=now()""",
            repo, worker, source, model, int(persisted), int(classification in {"success","no_work"}),
            int(classification not in {"success","no_work"}), run_id)
        if classification in MODEL_COOLDOWNS:
            status, until = "unavailable", observed + timedelta(seconds=MODEL_COOLDOWNS[classification])
        elif classification in TRANSIENT and source in MODEL_SCOPED_SOURCES:
            status, until = "cooling", _provider_cooldown(source, classification, observed)
        elif proven:
            status, until = "healthy", None
        else:
            status, until = "unknown", None
        if classification in MODEL_COOLDOWNS or (classification in TRANSIENT and source in MODEL_SCOPED_SOURCES) or proven:
            await conn.execute(
                """INSERT INTO public.factory_model_health
                     (repo,source,model,status,last_outcome,cooldown_until,last_verified_at,last_run_id)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT(repo,source,model) DO UPDATE SET
                     status=EXCLUDED.status,last_outcome=EXCLUDED.last_outcome,
                     cooldown_until=EXCLUDED.cooldown_until,
                     last_verified_at=EXCLUDED.last_verified_at,
                     last_run_id=EXCLUDED.last_run_id,updated_at=now()
                   WHERE factory_model_health.last_run_id <= EXCLUDED.last_run_id
                     AND factory_model_health.status != 'retired'""",
                repo, source, model, status, classification, until, observed if proven else None, run_id)
        if classification in TRANSIENT and source not in MODEL_SCOPED_SOURCES:
            until = _provider_cooldown(source, classification, observed)
            await conn.execute(
                """INSERT INTO public.factory_provider_budget
                     (repo,source,cooldown_until,quota_reset_at,last_outcome,last_run_id)
                   VALUES($1,$2,$3,$4,$5,$6)
                   ON CONFLICT(repo,source) DO UPDATE SET
                     cooldown_until=greatest(factory_provider_budget.cooldown_until,EXCLUDED.cooldown_until),
                     quota_reset_at=CASE WHEN EXCLUDED.quota_reset_at IS NOT NULL
                        THEN EXCLUDED.quota_reset_at ELSE factory_provider_budget.quota_reset_at END,
                     last_outcome=EXCLUDED.last_outcome,last_run_id=EXCLUDED.last_run_id,
                     updated_at=now()
                   WHERE factory_provider_budget.last_run_id<=EXCLUDED.last_run_id""",
                repo, source, until, until if classification=="provider_quota" else None, classification,run_id)
        # Provider success clears a transient breaker only if no later breaker
        # was recorded. Another concurrent worker may still have hit a limit.
        if proven and classification not in TRANSIENT:
            await conn.execute(
                """UPDATE public.factory_provider_budget SET cooldown_until=NULL,
                   last_outcome=$3,last_run_id=$4,updated_at=now()
                   WHERE repo=$1 AND source=$2 AND last_run_id <= $4""",
                repo, source, classification, run_id)
        kind = str(outcome.get("selected_kind") or "")
        number = str(outcome.get("selected_number") or "")
        if kind == "pr" and number.isdigit() and classification in {"work_failure","unknown_failure","environment_failure"}:
            key = f"factory-projection-v1:{repo}:pr:{int(number)}"
            record = await conn.fetchval(
                "SELECT payload->0->'item' FROM public.factory_state_kv WHERE cache_key=$1", key)
            if isinstance(record, str):
                record = json.loads(record)
            head = str((record or {}).get("headRefOid") or (record or {}).get("head_sha") or "")
            labels = (record or {}).get("labels") or []
            names = {v.get("name") if isinstance(v,dict) else str(v) for v in labels}
            stage = next((s for s in ("factory:changes-requested","factory:ci","factory:review")
                          if s in names), "factory:review")
            if HEAD_RE.fullmatch(head):
                seconds = 180 if classification == "work_failure" else 300 if classification == "unknown_failure" else 600
                await conn.execute(
                    """INSERT INTO public.factory_pr_stage_retry
                         (repo,pr_number,head_sha,stage,attempts,outcome,retry_after,last_run_id)
                       VALUES($1,$2,$3,$4,1,$5,now()+$6::int * interval '1 second',$7)
                       ON CONFLICT(repo,pr_number,head_sha,stage) DO UPDATE SET
                         attempts=factory_pr_stage_retry.attempts+1,outcome=EXCLUDED.outcome,
                         retry_after=EXCLUDED.retry_after,
                         last_run_id=greatest(factory_pr_stage_retry.last_run_id,EXCLUDED.last_run_id),
                         updated_at=now()
                       WHERE factory_pr_stage_retry.last_run_id < EXCLUDED.last_run_id""",
                    repo, int(number), head, stage, classification, seconds, run_id)
    return True


def record_runtime(repo: str, run_id: int, outcome: dict[str, Any]) -> bool:
    if not enabled():
        raise RuntimeError("trusted runtime requires restricted Neon connection")
    return _run(project_runtime, repo, run_id, outcome)


async def _eligibility(conn: Any, repo: str, workers: list[str]) -> tuple[list[str],list[str]]:
    roster = _roster()
    rows = await conn.fetch(
        """SELECT source,model,status,cooldown_until FROM public.factory_model_health WHERE repo=$1""",repo)
    models = {(r["source"],r["model"]):r for r in rows}
    budgets = {r["source"]:r for r in await conn.fetch(
        "SELECT * FROM public.factory_provider_budget WHERE repo=$1",repo)}
    counts = {r["source"]:r["n"] for r in await conn.fetch(
        """SELECT source,count(*) n FROM public.factory_provider_reservation
           WHERE repo=$1 AND expires_at>now() GROUP BY source""",repo)}
    now = datetime.now(timezone.utc)
    kept, rejected = [], []
    for worker in workers:
        pair = roster.get(worker)
        if pair is None:
            rejected.append(f"{worker}: missing trusted roster entry")
            continue
        source,model = pair
        m,b = models.get(pair),budgets.get(source)
        if m and (m["status"]=="retired" or (m["status"] in {"unavailable","cooling"}
                    and m["cooldown_until"] and m["cooldown_until"]>now)):
            rejected.append(f"{worker}: model {model} {m['status']}")
        elif b and b["cooldown_until"] and b["cooldown_until"]>now:
            rejected.append(f"{worker}: provider {source} cooling")
        elif b and b["concurrency_limit"] is not None and counts.get(source,0)>=b["concurrency_limit"]:
            rejected.append(f"{worker}: provider {source} full")
        elif b and b["daily_limit"] is not None and b["usage_day"]==now.date() and b["daily_used"]>=b["daily_limit"]:
            rejected.append(f"{worker}: provider {source} daily budget exhausted")
        else:
            kept.append(worker)
    return kept, rejected


def filter_workers(repo: str, workers: list[str]) -> tuple[list[str],list[str]]:
    if not enabled():
        return workers, ["Neon unavailable; existing lease checks still required"]
    return _run(_eligibility,repo,workers)


async def reserve_capacity(conn: Any, repo: str, worker: str, claim_id: str, ttl: int) -> bool:
    """Called inside the existing exclusive repo lease transaction."""
    roster=_roster()
    if worker not in roster:
        return False
    kept,_=await _eligibility(conn,repo,[worker])
    if not kept:
        return False
    source, _ = roster[worker]
    # The checked-in source policy remains authoritative; never invent a quota
    # for unmetered providers. Check it under the same repo advisory lock.
    from factory_source_budget import load_budgets
    from factory_source_budget import PROTECTED_WORKERS
    cap=None if int(worker) in PROTECTED_WORKERS else load_budgets().get(source)
    if cap is not None and (await _daily_usage(conn,repo,[source]))[source] >= cap:
        return False
    row = await conn.fetchrow(
        "SELECT daily_limit,usage_day,daily_used FROM public.factory_provider_budget WHERE repo=$1 AND source=$2 FOR UPDATE",
        repo,source)
    if row and row["daily_limit"] is not None and row["usage_day"]==datetime.now(timezone.utc).date() and row["daily_used"]>=row["daily_limit"]:
        return False
    await conn.execute(
        """INSERT INTO public.factory_provider_reservation
             (claim_id,repo,worker,source,expires_at)
           VALUES($1::uuid,$2,$3,$4,now()+$5::int * interval '1 second')""",
        claim_id,repo,worker,source,ttl)
    await conn.execute(
        """INSERT INTO public.factory_provider_budget(repo,source,usage_day,daily_used)
           VALUES($1,$2,(now() AT TIME ZONE 'UTC')::date,1)
           ON CONFLICT(repo,source) DO UPDATE SET
            daily_used=CASE WHEN factory_provider_budget.usage_day=(now() AT TIME ZONE 'UTC')::date
                            THEN factory_provider_budget.daily_used+1 ELSE 1 END,
            usage_day=(now() AT TIME ZONE 'UTC')::date,updated_at=now()""",repo,source)
    return True


async def release_capacity(conn: Any, claim_id: str) -> None:
    await conn.execute("DELETE FROM public.factory_provider_reservation WHERE claim_id=$1::uuid",claim_id)


async def _daily_usage(conn: Any, repo: str, sources: list[str]) -> dict[str,int]:
    # Assignments are committed in the SAME transaction as capacity claims,
    # and carry verified worker IDs. This avoids an Actions-wide daily scan.
    since=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
    rows=await conn.fetch(
        """SELECT detail->>'worker' AS worker
           FROM public.factory_state_events
           WHERE event_type='worker_assigned' AND created_at >= $1""",since)
    roster=_roster()
    counts={source:0 for source in sources}
    for row in rows:
        pair=roster.get(str(row["worker"] or ""))
        if pair and pair[0] in counts:
            counts[pair[0]]+=1
    return counts


def daily_usage(repo: str, sources: list[str]) -> dict[str,int] | None:
    if not enabled():
        return None
    return _run(_daily_usage,repo,sources)


async def _seed_daily(conn: Any, repo: str, counts: dict[str,int]) -> None:
    for source,count in counts.items():
        if count<0:
            raise ValueError("negative usage")
        await conn.execute(
            """INSERT INTO public.factory_provider_budget(repo,source,usage_day,daily_used)
               VALUES($1,$2,(now() AT TIME ZONE 'UTC')::date,$3)
               ON CONFLICT(repo,source) DO UPDATE SET
                 usage_day=EXCLUDED.usage_day,daily_used=EXCLUDED.daily_used,updated_at=now()
               WHERE factory_provider_budget.usage_day <> EXCLUDED.usage_day""",repo,source,count)


def seed_daily(repo: str, counts: dict[str,int]) -> None:
    if enabled():
        _run(_seed_daily,repo,counts)


async def _cooling_prs(conn: Any, repo: str, heads: dict[int,tuple[str,str]]) -> set[int]:
    rows=await conn.fetch(
        """SELECT pr_number,head_sha,stage FROM public.factory_pr_stage_retry
           WHERE repo=$1 AND retry_after>now()""",repo)
    return {int(r["pr_number"]) for r in rows
            if heads.get(int(r["pr_number"]))==(r["head_sha"],r["stage"])}


def cooling_prs(repo: str, heads: dict[int,tuple[str,str]]) -> set[int]:
    return _run(_cooling_prs,repo,heads) if enabled() and heads else set()


async def _ingest_check(conn: Any, repo: str, event: dict[str,Any]) -> int:
    run=event.get("workflow_run") or {}
    sha=str(run.get("head_sha") or "")
    if not HEAD_RE.fullmatch(sha) or run.get("status")!="completed":
        return 0
    name=str(run.get("name") or "")[:160]
    conclusion=str(run.get("conclusion") or "unknown")[:60]
    number=int(run.get("id") or 0)
    observed=datetime.now(timezone.utc)
    count=0
    for pr in run.get("pull_requests") or []:
        pr_num=pr.get("number") if isinstance(pr,dict) else None
        if not isinstance(pr_num,int) or pr_num<=0:
            continue
        await conn.execute(
            """INSERT INTO public.factory_check_projection
                 (repo,pr_number,head_sha,check_name,conclusion,run_id,observed_at)
               VALUES($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT(repo,pr_number,head_sha,check_name) DO UPDATE SET
                 conclusion=EXCLUDED.conclusion,run_id=EXCLUDED.run_id,observed_at=EXCLUDED.observed_at
               WHERE factory_check_projection.run_id<=EXCLUDED.run_id""",
            repo,pr_num,sha,name,conclusion,number,observed)
        if name in {"PR-Agent Advisory Review","Local Ollama Review"} and conclusion=="failure":
            await conn.execute(
                """INSERT INTO public.factory_pr_stage_retry
                     (repo,pr_number,head_sha,stage,attempts,outcome,retry_after,last_run_id)
                   VALUES($1,$2,$3,'factory:review',1,'review_transport_failure',
                          now()+interval '5 minutes',$4)
                   ON CONFLICT(repo,pr_number,head_sha,stage) DO UPDATE SET
                     attempts=factory_pr_stage_retry.attempts+1,
                     outcome=EXCLUDED.outcome,retry_after=EXCLUDED.retry_after,
                     last_run_id=EXCLUDED.last_run_id,updated_at=now()
                   WHERE factory_pr_stage_retry.last_run_id<EXCLUDED.last_run_id""",
                repo,pr_num,sha,number)
        count+=1
    return count


def ingest_check(repo: str, event: dict[str,Any]) -> int:
    if not enabled():
        return 0
    return _run(_ingest_check,repo,event)


async def _checkpoint(conn: Any, repo: str, scope: str, cursor: str, changes: int) -> None:
    await conn.execute(
        """INSERT INTO public.factory_reconciliation_cursor
             (repo,scope,checkpoint,changed_count)
           VALUES($1,$2,$3,$4)
           ON CONFLICT(repo,scope) DO UPDATE SET checkpoint=EXCLUDED.checkpoint,
             changed_count=EXCLUDED.changed_count,checked_at=now()""",
        repo,scope,cursor,changes)


def checkpoint(repo: str, scope: str, cursor: str, changes: int=0) -> None:
    if enabled():
        _run(_checkpoint,repo,scope,cursor,changes)


async def _stats(conn:Any,repo:str)->dict[str,Any]:
    rows=await conn.fetch(
        """SELECT worker,source,model,attempts,productive,completed,failures
           FROM public.factory_worker_metrics WHERE repo=$1 ORDER BY productive DESC,attempts DESC LIMIT 100""",repo)
    return {"workers":[dict(r) for r in rows],
            "cooling": [dict(r) for r in await conn.fetch(
                """SELECT source,model,status,cooldown_until FROM public.factory_model_health
                   WHERE repo=$1 AND cooldown_until>now() ORDER BY cooldown_until""",repo)]}




async def _sync_registry(conn: Any, repo: str, comments: list[dict[str,Any]]) -> int:
    # Convert only trusted #1093 evidence; never trust model-agent content.
    from factory_candidate_health import latest_attempt_evidence
    evidence=latest_attempt_evidence(comments)
    inserted=0
    for (source,model),item in evidence.items():
        if not source or not model or item.outcome in {"unknown_failure","control_plane_failure","environment_failure"}:
            continue
        if item.outcome == "model_retired_410":
            status,until="retired",None
        elif item.outcome in MODEL_COOLDOWNS:
            status,until="unavailable",datetime.fromtimestamp(item.updated+MODEL_COOLDOWNS[item.outcome],timezone.utc)
        elif item.outcome in TRANSIENT and source in MODEL_SCOPED_SOURCES:
            status,until="cooling",datetime.fromtimestamp(item.updated+TRANSIENT[item.outcome],timezone.utc)
        elif item.outcome in TRANSIENT:
            status,until="unknown",None
        elif item.outcome in {"success","no_work","work_failure"}:
            status,until="healthy",None
        else:
            continue
        result=await conn.fetchval(
            """INSERT INTO public.factory_model_health
                (repo,source,model,status,last_outcome,cooldown_until,last_verified_at)
               VALUES($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT DO NOTHING RETURNING model""",
            repo,source,model,status,item.outcome,until,
            datetime.fromtimestamp(item.updated,timezone.utc) if status=="healthy" else None)
        inserted+=int(result is not None)
        if item.outcome in TRANSIENT and source not in MODEL_SCOPED_SOURCES:
            observed=datetime.fromtimestamp(item.updated,timezone.utc)
            until=_provider_cooldown(source,item.outcome,observed)
            if until and until>datetime.now(timezone.utc):
                await conn.execute(
                    """INSERT INTO public.factory_provider_budget
                         (repo,source,cooldown_until,quota_reset_at,last_outcome)
                       VALUES($1,$2,$3,$4,$5)
                       ON CONFLICT(repo,source) DO UPDATE SET
                         cooldown_until=greatest(factory_provider_budget.cooldown_until,
                                                 EXCLUDED.cooldown_until),
                         quota_reset_at=EXCLUDED.quota_reset_at,last_outcome=EXCLUDED.last_outcome,
                         updated_at=now()
                       WHERE factory_provider_budget.last_run_id=0""",
                    repo,source,until,until if item.outcome=="provider_quota" else None,item.outcome)
    return inserted


def sync_registry(repo: str, comments: list[dict[str,Any]]) -> int:
    if not enabled():
        return 0
    return _run(_sync_registry,repo,comments)


async def _sync_catalog(conn:Any,repo:str,report:dict[str,Any])->int:
    """Record trusted catalog absence without editing the checked-in roster."""
    count=0
    for item in report.get("retirements") or []:
        if not isinstance(item,dict):
            continue
        source,model=str(item.get("source") or ""),str(item.get("model") or "")
        if not source or not model:
            continue
        reason=str(item.get("reason") or "")
        retired="410" in reason or "permanently retired" in reason
        await conn.execute(
            """INSERT INTO public.factory_model_health
                (repo,source,model,status,last_outcome,cooldown_until)
               VALUES($1,$2,$3,$4,$5,$6)
               ON CONFLICT(repo,source,model) DO UPDATE SET
                 status=EXCLUDED.status,last_outcome=EXCLUDED.last_outcome,
                 cooldown_until=EXCLUDED.cooldown_until,updated_at=now()
               WHERE factory_model_health.status!='retired'""",
            repo,source,model,"retired" if retired else "unavailable",
            "model_retired_410" if retired else "model_unavailable",
            None if retired else datetime.now(timezone.utc)+timedelta(hours=6))
        count+=1
    # A later successful catalog read proves availability, not invocation.
    # Clear an expired absence without claiming the model executed correctly.
    for item in report.get("kept") or []:
        if not isinstance(item,dict):
            continue
        source,model=str(item.get("source") or ""),str(item.get("model") or "")
        if source and model:
            await conn.execute(
                """UPDATE public.factory_model_health SET status='unknown',
                   cooldown_until=NULL,updated_at=now()
                   WHERE repo=$1 AND source=$2 AND model=$3 AND status='unavailable'
                     AND last_outcome='model_unavailable'""",repo,source,model)
    return count


def sync_catalog(repo:str,report:dict[str,Any])->int:
    return _run(_sync_catalog,repo,report) if enabled() else 0


async def _rank_workers(conn:Any,repo:str,workers:list[str])->list[str]:
    roster=_roster()
    rows=await conn.fetch(
        """SELECT worker,sum(attempts)::int AS attempts,sum(productive)::int AS productive
           FROM public.factory_worker_metrics WHERE repo=$1 GROUP BY worker""",repo)
    scores={str(r["worker"]):(int(r["productive"]),int(r["attempts"])) for r in rows}
    groups:dict[str,list[tuple[int,str]]]={}
    for index,w in enumerate(workers):
        source=roster.get(w,("unknown",""))[0]
        groups.setdefault(source,[]).append((index,w))
    for source,entries in groups.items():
        # Keep the source-diverse cadence/slot positions. Order ONLY within
        # each source, with unsampled workers remaining neutral.
        sorted_workers=sorted((w for _,w in entries),key=lambda w:(
            -((scores[w][0]/scores[w][1]) if w in scores and scores[w][1]>=3 else 0.20),
            w))
        for (position,_),replacement in zip(entries,sorted_workers):
            workers[position]=replacement
    return workers


def rank_workers(repo:str,workers:list[str])->list[str]:
    return _run(_rank_workers,repo,workers) if enabled() else workers



async def _claim_wakeup(conn: Any, repo: str, scope: str, interval_seconds: int) -> bool:
    # Every event worker races on one row, no additional GitHub-wide polling.
    row=await conn.fetchval(
        """INSERT INTO public.factory_reconciliation_cursor(repo,scope,checkpoint)
           VALUES($1,$2,'event-wakeup')
           ON CONFLICT(repo,scope) DO UPDATE SET
             checked_at=now(),checkpoint=EXCLUDED.checkpoint
           WHERE factory_reconciliation_cursor.checked_at
               < now()-$3::int * interval '1 second'
           RETURNING scope""",repo,scope,interval_seconds)
    return row is not None


def claim_wakeup(repo: str, scope: str, interval_seconds: int=120) -> bool:
    return _run(_claim_wakeup,repo,scope,interval_seconds) if enabled() else False

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("bootstrap","filter","rank","stats","ingest-check","checkpoint","sync-catalog","sync-registry"))
    parser.add_argument("--repo",default=os.environ.get("GITHUB_REPOSITORY","JoshCLWren/comic-pile"))
    parser.add_argument("--file",type=Path)
    parser.add_argument("--scope")
    parser.add_argument("--cursor",default="")
    args=parser.parse_args()
    if not REPO_RE.fullmatch(args.repo):
        parser.error("invalid repo")
    if args.command=="bootstrap":
        if not enabled():
            raise SystemExit("Neon is required for factory operations")
        _run(lambda conn: conn.fetchval("SELECT 1"))
        # One-time migration from trusted #1093 evidence. The checkpoint
        # prevents rebuilding the entire model table on every dispatch.
        async def needs_backfill(conn:Any,repo:str)->bool:
            return await conn.fetchval(
                "SELECT 1 FROM public.factory_reconciliation_cursor WHERE repo=$1 AND scope='registry-backfill-v1'",
                repo) is None
        if _run(needs_backfill,args.repo):
            from factory_completion_controller import registry_comments
            records=registry_comments()
            n=sync_registry(args.repo,records)
            checkpoint(args.repo,"registry-backfill-v1",datetime.now(timezone.utc).isoformat(),n)
            print(f"[factory-operations] imported {n} trusted model records")
        print("[factory-operations] schema ready")
    elif args.command=="filter":
        workers=[str(w) for w in json.load(sys.stdin)]
        kept,denied=filter_workers(args.repo,workers)
        for reason in denied:
            print(f"[factory-operations] {reason}",file=sys.stderr)
        print(json.dumps(kept,separators=(",",":")))
    elif args.command=="rank":
        print(json.dumps(rank_workers(args.repo,[str(w) for w in json.load(sys.stdin)]),
                         separators=(",",":")))
    elif args.command=="sync-catalog":
        if args.file is None:
            parser.error("--file required")
        print(json.dumps({"missing_models":sync_catalog(args.repo,json.loads(args.file.read_text()))}))
    elif args.command=="sync-registry":
        if args.file is None:
            parser.error("--file required")
        print(json.dumps({"backfilled":sync_registry(args.repo,json.loads(args.file.read_text()))}))
    elif args.command=="stats":
        print(json.dumps(_run(_stats,args.repo),default=str))
    elif args.command=="ingest-check":
        if args.file is None:
            parser.error("--file required")
        changed=ingest_check(args.repo,json.loads(args.file.read_text()))
        wake=claim_wakeup(args.repo,"ci-review-wakeup",120) if changed else False
        print(json.dumps({"projected":changed,"wake":wake}))
    elif args.command=="checkpoint":
        if not args.scope:
            parser.error("--scope required")
        checkpoint(args.repo,args.scope,args.cursor)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
