"""Transactional Neon worker leases and lifecycle events for trusted controllers.

Uses the already provisioned factory_state database. No secrets reach model-runner
jobs: only trusted dispatcher, completion collector, and runtime observer call this.
GitHub still authorizes issue labels, exact-head reviews, checks, and merges.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from factory_state_cache import _dsn

WORKER_RE = re.compile(r"^[0-9]+$")
HEARTBEAT_RE = re.compile(r"<!-- factory-heartbeat:v1 worker=opencode-free-model-factory-(\d+) -->")
RUN_RE = re.compile(r"(?m)^Run:\s*(\d+)\s*$")
OUTCOME_RE = re.compile(r"(?m)^Outcome:\s*([^\n]+)")
LEASE_PREFIX = "factory-lease-v1:"


def enabled() -> bool:
    return bool(os.environ.get("FACTORY_STATE_DSN_FILE"))


def _keys(repo: str, worker: str, numbers: list[int]) -> list[str]:
    return [f"{LEASE_PREFIX}{repo}:worker:{worker}"] + [
        f"{LEASE_PREFIX}{repo}:target:{number}" for number in sorted(set(numbers))
    ]


async def _acquire(repo: str, worker: str, numbers: list[int], ttl: int) -> str | None:
    import asyncpg

    token = str(uuid.uuid4())
    keys = _keys(repo, worker, numbers)
    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    try:
        async with conn.transaction():
            # A repository-level transaction lock makes worker and *all* linked
            # issue/PR target rows one indivisible claim across Actions jobs.
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", LEASE_PREFIX + repo)
            busy = await conn.fetch(
                """SELECT cache_key FROM public.factory_state_kv
                   WHERE cache_key = ANY($1::text[]) AND expires_at > now()""",
                keys,
            )
            if busy:
                return None
            from factory_state_operations import _roster, reserve_capacity
            if not await reserve_capacity(conn, repo, worker, token, ttl):
                return None
            payload = json.dumps([{
                "claim_id": token, "worker": worker, "targets": sorted(set(numbers)),
            }])
            for key in keys:
                await conn.execute(
                    """INSERT INTO public.factory_state_kv
                         (cache_key, payload, fetched_at, expires_at, updated_at)
                       VALUES ($1, $2::jsonb, now(), now() + $3::int * interval '1 second', now())
                       ON CONFLICT (cache_key) DO UPDATE SET
                         payload=EXCLUDED.payload, fetched_at=EXCLUDED.fetched_at,
                         expires_at=EXCLUDED.expires_at, updated_at=now(),
                         refresh_owner=NULL, refresh_until=NULL""",
                    key, payload, ttl,
                )
            await conn.execute(
                """INSERT INTO public.factory_state_events
                   (source, event_type, subject_type, subject_number, detail)
                   VALUES ('github-actions', 'worker_assigned', 'worker', $1,
                     jsonb_build_object('claim_id', $2::text, 'worker', $3::text,
                                        'targets', $4::jsonb, 'run_id', $5::text,
                                        'source', $6::text))""",
                int(worker), token, worker, json.dumps(sorted(set(numbers))),
                os.environ.get("GITHUB_RUN_ID", ""),
                _roster()[worker][0],
            )
        return token
    finally:
        await conn.close()


def acquire_lease(repo: str, worker: str, numbers: list[int], ttl: int = 900) -> str | None:
    """Return claim UUID on success, None on conflict, '' without Neon.

    In trusted Actions with a configured DSN, connection failures are fatal:
    silently falling back after a failed database claim would split ownership.
    """
    if not WORKER_RE.fullmatch(worker) or not numbers or any(n <= 0 for n in numbers):
        raise ValueError("invalid factory lease target or worker")
    if not 60 <= ttl <= 86400:
        raise ValueError("invalid factory lease TTL")
    if not enabled():
        if os.environ.get("FACTORY_NEON_LEASE_REQUIRED") == "true":
            raise RuntimeError("trusted factory dispatcher requires Neon transaction lease connection")
        return ""
    return asyncio.run(_acquire(repo, worker, numbers, ttl))


async def _release(repo: str, worker: str, token: str, reason: str) -> bool:
    import asyncpg

    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", LEASE_PREFIX + repo)
            worker_key = _keys(repo, worker, [])[0]
            row = await conn.fetchrow(
                """SELECT payload FROM public.factory_state_kv
                   WHERE cache_key=$1 AND payload->0->>'claim_id'=$2""",
                worker_key, token,
            )
            if row is None:
                return False
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            numbers = payload[0]["targets"]
            keys = _keys(repo, worker, numbers)
            await conn.execute(
                """DELETE FROM public.factory_state_kv
                   WHERE cache_key=ANY($1::text[])
                     AND payload->0->>'claim_id'=$2""",
                keys, token,
            )
            from factory_state_operations import release_capacity
            await release_capacity(conn, token)
            await conn.execute(
                """INSERT INTO public.factory_state_events
                   (source, event_type, subject_type, subject_number, detail)
                   VALUES ('github-actions', 'worker_released', 'worker', $1,
                     jsonb_build_object('claim_id',$2::text,'worker',$3::text,
                                        'reason',$4::text,'targets',$5::jsonb))""",
                int(worker), token, worker, reason, json.dumps(numbers),
            )
        return True
    finally:
        await conn.close()


def release_lease(repo: str, worker: str, token: str, reason: str) -> bool:
    if not enabled() or not token:
        return False
    return asyncio.run(_release(repo, worker, token, reason))


def release_worker(repo: str, worker: str, reason: str) -> bool:
    """Release a verified worker's Neon claim after GitHub labels are released."""
    if not enabled():
        return False

    async def _lookup() -> str | None:
        import asyncpg
        conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
        try:
            row = await conn.fetchrow(
                "SELECT payload FROM public.factory_state_kv WHERE cache_key=$1",
                _keys(repo, worker, [])[0],
            )
            if not row:
                return None
            value = row["payload"]
            if isinstance(value, str):
                value = json.loads(value)
            return str(value[0]["claim_id"])
        finally:
            await conn.close()

    token = asyncio.run(_lookup())
    return release_lease(repo, worker, token, reason) if token else False


async def _events(repo: str, entries: list[dict[str, Any]]) -> int:
    import asyncpg

    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    inserted = 0
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", LEASE_PREFIX + repo)
            for entry in entries:
                existing = await conn.fetchval(
                    """SELECT 1 FROM public.factory_state_events
                       WHERE source='github-actions'
                         AND detail->>'event_id'=$1 LIMIT 1""",
                    entry["event_id"],
                )
                if existing:
                    continue
                await conn.execute(
                    """INSERT INTO public.factory_state_events
                       (source,event_type,subject_type,subject_number,detail)
                       VALUES ('github-actions',$1,'worker',$2,$3::jsonb)""",
                    entry["event_type"], int(entry["worker"]), json.dumps(entry),
                )
                inserted += 1
                # 'running' is an initial status marker, not a periodic
                # liveness check. A terminal success/failure never renews.
                if entry["event_type"] == "worker_started":
                    worker_key = _keys(repo, entry["worker"], [])[0]
                    row = await conn.fetchrow(
                        """SELECT payload FROM public.factory_state_kv
                           WHERE cache_key=$1 AND expires_at>now()""",
                        worker_key,
                    )
                    if row:
                        payload = row["payload"]
                        if isinstance(payload, str):
                            payload = json.loads(payload)
                        token = payload[0]["claim_id"]
                        await conn.execute(
                            """UPDATE public.factory_provider_reservation
                               SET expires_at=now()+interval '15 minutes'
                               WHERE claim_id=$1::uuid""", token,
                        )
                        await conn.execute(
                            """UPDATE public.factory_state_kv SET
                                 expires_at=now() + interval '15 minutes',
                                 updated_at=now()
                               WHERE cache_key=$1 AND payload->0->>'claim_id'=$2""",
                            worker_key, token,
                        )
                        await conn.execute(
                            """UPDATE public.factory_state_kv SET
                                 expires_at=now() + interval '15 minutes',
                                 updated_at=now()
                               WHERE cache_key LIKE $1
                                 AND payload->0->>'claim_id'=$2""",
                            f"{LEASE_PREFIX}{repo}:target:%", token,
                        )
        return inserted
    finally:
        await conn.close()



async def _renew_verified(repo: str, workers: list[str]) -> int:
    """Extend existing, unexpired reservations for verified running workers."""
    import asyncpg

    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=12)
    renewed = 0
    try:
        async with conn.transaction():
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                LEASE_PREFIX + repo,
            )
            for worker in sorted(set(workers)):
                worker_key = _keys(repo, worker, [])[0]
                raw = await conn.fetchval(
                    """SELECT payload FROM public.factory_state_kv
                       WHERE cache_key=$1 AND expires_at>now()""",
                    worker_key,
                )
                if raw is None:
                    continue
                payload = json.loads(raw) if isinstance(raw, str) else raw
                token = payload[0]["claim_id"]
                await conn.execute(
                    """UPDATE public.factory_provider_reservation
                       SET expires_at=now()+interval '15 minutes'
                       WHERE claim_id=$1::uuid""", token)
                await conn.execute(
                    """UPDATE public.factory_state_kv
                       SET expires_at=now() + interval '15 minutes',
                           updated_at=now()
                       WHERE expires_at>now()
                         AND payload->0->>'claim_id'=$1
                         AND (cache_key=$2 OR cache_key LIKE $3)""",
                    token, worker_key, f"{LEASE_PREFIX}{repo}:target:%",
                )
                renewed += 1
        return renewed
    finally:
        await conn.close()


def renew_verified_workers(repo: str, workers: list[str]) -> int:
    """Renew only workers verified alive by the trusted GitHub Actions controller.

    Args:
        repo: Repository whose worker claims are being extended.
        workers: Numeric worker IDs observed in active GitHub Actions runs.

    Returns:
        Number of unexpired worker claim groups extended.
    """
    if not enabled() or not workers:
        return 0
    if any(not WORKER_RE.fullmatch(worker) for worker in workers):
        raise ValueError("invalid verified worker ID")
    return asyncio.run(_renew_verified(repo, workers))


def worker_claim(repo: str, worker: str) -> tuple[str, list[int]] | None:
    """Capture the existing claim before a controller mutates ownership labels.

    Args:
        repo: GitHub repository.
        worker: Numeric factory worker identifier.

    Returns:
        Existing claim ID and target numbers, or None if unavailable.

    A token-bound release cannot remove a claim acquired after this snapshot.
    """
    if not enabled():
        return None

    async def _read() -> tuple[str, list[int]] | None:
        import asyncpg

        conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
        try:
            raw = await conn.fetchval(
                "SELECT payload FROM public.factory_state_kv WHERE cache_key=$1",
                _keys(repo, worker, [])[0],
            )
            if raw is None:
                return None
            payload = json.loads(raw) if isinstance(raw, str) else raw
            return str(payload[0]["claim_id"]), [
                int(number) for number in payload[0]["targets"]
            ]
        finally:
            await conn.close()

    return asyncio.run(_read())

def record_events(repo: str, entries: list[dict[str, Any]]) -> int:
    if not enabled() or not entries:
        return 0
    return asyncio.run(_events(repo, entries))


def record_heartbeat_comments(repo: str, changes: list[dict[str, Any]]) -> int:
    """Ingest only trusted, recent GitHub heartbeat updates, keyed by run/status.

    Repeated incremental reads are idempotent. Models never get database access.
    """
    from factory_work_policy import comment_is_trusted

    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    events = []
    for comment in changes:
        if not isinstance(comment, dict) or not comment_is_trusted(comment):
            continue
        body = str(comment.get("body") or "")
        worker = HEARTBEAT_RE.search(body)
        run = RUN_RE.search(body)
        outcome = OUTCOME_RE.search(body)
        updated = str(comment.get("updated_at") or "")
        if not worker or not run or not outcome or not updated:
            continue
        try:
            stamp = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp < cutoff:
            continue
        status = outcome.group(1).strip().lower()
        event_type = (
            "worker_started" if status == "running"
            else "worker_outcome_signal" if status in {"success", "failure"}
            else "worker_heartbeat"
        )
        events.append({
            "event_type": event_type,
            "event_id": f"heartbeat:{comment.get('id')}:{updated}:{status}",
            "worker": worker.group(1),
            "run_id": run.group(1),
            "status": status,
            "observed_at": updated,
        })
    return record_events(repo, events)


def record_runtime_outcome(repo: str, run_id: str, outcome: dict[str, Any]) -> int:
    worker = str(outcome.get("worker") or "")
    if not WORKER_RE.fullmatch(worker) or not run_id.isdecimal():
        raise ValueError("invalid trusted runtime outcome identity")
    status = str(outcome.get("outcome_class") or "unknown_failure")
    event_type = "worker_completed" if status in {"success", "no_work"} else "worker_failed"
    inserted = record_events(repo, [{
        "event_type": event_type,
        "event_id": f"runtime:{run_id}",
        "worker": worker,
        "run_id": run_id,
        "source": outcome.get("source"),
        "model": outcome.get("model"),
        "exact_model_proven": outcome.get("exact_model_proven") is True,
        "outcome_class": status,
        "selected_kind": outcome.get("selected_kind"),
        "selected_number": outcome.get("selected_number"),
        "persisted_work": bool(outcome.get("persisted_work")),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }])
    # Separate projection key is idempotent across both trusted outcome writers.
    from factory_state_operations import enabled as health_enabled, record_runtime
    if health_enabled():
        record_runtime(repo, int(run_id), outcome)
    return inserted


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["runtime-outcome"])
    parser.add_argument("--file", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "JoshCLWren/comic-pile"))
    args = parser.parse_args()
    if args.command == "runtime-outcome":
        with open(args.file, encoding="utf-8") as stream:
            result = record_runtime_outcome(args.repo, args.run_id, json.load(stream))
        print(f"[factory-ledger] recorded {result} terminal worker event(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
