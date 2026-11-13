"""Event-maintained issue/PR projections with periodic GitHub drift repair.

This runs only in trusted Actions jobs. It reads/writes the existing isolated
factory_state KV and event tables; webhook payloads are normalized, not executed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from factory_state_cache import _dsn

PREFIX = "factory-projection-v1:"
RECONCILE_SECONDS = 1800


def enabled() -> bool:
    return bool(os.environ.get("FACTORY_STATE_DSN_FILE"))


def _prefix(repo: str, kind: str) -> str:
    if kind not in ("issue", "pr"):
        raise ValueError("unknown factory projection kind")
    return f"{PREFIX}{repo}:{kind}:"


def _marker(repo: str, kind: str) -> str:
    return _prefix(repo, kind) + "_full_snapshot"


def _target_key(repo: str, kind: str, number: int) -> str:
    return _prefix(repo, kind) + str(number)


def _object(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def normalize_event(event: dict[str, Any]) -> tuple[str, int, dict[str, Any], str] | None:
    """Convert a GitHub issues/pull_request_target payload to gh CLI list shape."""
    is_pr = "pull_request" in event
    raw = event.get("pull_request") if is_pr else event.get("issue")
    if not isinstance(raw, dict) or not isinstance(raw.get("number"), int):
        return None
    kind = "pr" if is_pr else "issue"
    labels = [{"name": label.get("name")} for label in raw.get("labels", [])
              if isinstance(label, dict) and isinstance(label.get("name"), str)]
    base = {
        "number": raw["number"],
        "title": raw.get("title") or "",
        "body": raw.get("body") or "",
        "labels": labels,
        "createdAt": raw.get("created_at") or "",
        "updatedAt": raw.get("updated_at") or "",
    }
    if is_pr:
        head = raw.get("head") or {}
        base.update({
            "headRefName": head.get("ref") or "",
            "headRefOid": head.get("sha") or "",
            "isDraft": bool(raw.get("draft")),
            "mergeable": raw.get("mergeable"),
            "mergeStateStatus": str(raw.get("mergeable_state") or "UNKNOWN").upper(),
            "isCrossRepository": ((head.get("repo") or {}).get("full_name") !=
                                  (raw.get("base") or {}).get("repo", {}).get("full_name")),
        })
    return kind, int(raw["number"]), base, str(raw.get("state") or "open").lower()


async def _read_projection(repo: str, kind: str) -> list[dict[str, Any]] | None:
    import asyncpg

    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    try:
        marker = await conn.fetchval(
            """SELECT fetched_at > now() - $2::int * interval '1 second'
               FROM public.factory_state_kv WHERE cache_key=$1""",
            _marker(repo, kind), RECONCILE_SECONDS,
        )
        if marker is not True:
            return None
        rows = await conn.fetch(
            """SELECT payload->0->'item' AS item
               FROM public.factory_state_kv
               WHERE cache_key LIKE $1 AND payload->0->>'state'='open'
               ORDER BY (payload->0->'item'->>'number')::bigint""",
            _prefix(repo, kind) + "%",
        )
        return [_object(row["item"]) for row in rows]
    finally:
        await conn.close()


def projected_json(repo: str, kind: str) -> list[dict[str, Any]] | None:
    """Return a complete, recently reconciled projection or None to bootstrap."""
    if not enabled():
        return None
    try:
        return asyncio.run(_read_projection(repo, kind))
    except Exception as exc:
        print(f"[factory-projection] read unavailable; using GitHub discovery ({type(exc).__name__})", file=sys.stderr)
        return None


async def _snapshot(repo: str, kind: str, items: list[dict[str, Any]], started: str) -> tuple[int, int]:
    import asyncpg

    if not all(isinstance(item, dict) and isinstance(item.get("number"), int) for item in items):
        raise ValueError("invalid GitHub list snapshot")
    prefix = _prefix(repo, kind)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    projection = [{
        "key": _target_key(repo, kind, int(item["number"])),
        "item": item,
        "source_updated_at": str(item.get("updatedAt") or ""),
        "observed_at": now,
    } for item in items]
    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=12)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", prefix)
            updated = await conn.fetch(
                """WITH incoming AS (
                    SELECT value->>'key' AS cache_key, value->'item' AS item,
                           value->>'source_updated_at' AS source_updated_at,
                           value->>'observed_at' AS observed_at
                    FROM jsonb_array_elements($1::jsonb)
                   )
                   INSERT INTO public.factory_state_kv
                     (cache_key,payload,fetched_at,expires_at,updated_at)
                   SELECT cache_key,
                     jsonb_build_array(jsonb_build_object('item',item,'state','open',
                       'source_updated_at',source_updated_at,'observed_at',observed_at)),
                     now(), '2100-01-01'::timestamptz, now()
                   FROM incoming
                   ON CONFLICT (cache_key) DO UPDATE SET
                     payload=EXCLUDED.payload,updated_at=now(),fetched_at=now()
                   WHERE (factory_state_kv.payload->0->>'source_updated_at')
                         <= (EXCLUDED.payload->0->>'source_updated_at')
                     AND (factory_state_kv.payload->0->'item'
                          IS DISTINCT FROM EXCLUDED.payload->0->'item'
                          OR factory_state_kv.payload->0->>'state' != 'open')
                   RETURNING cache_key""",
                json.dumps(projection),
            )
            removed = await conn.fetch(
                """UPDATE public.factory_state_kv SET
                     payload=jsonb_set(
                       jsonb_set(payload,'{0,state}','"closed"'::jsonb),
                       '{0,source_updated_at}',to_jsonb($3::text)),
                     updated_at=now()
                   WHERE cache_key LIKE $1
                     AND cache_key != $2
                     AND payload->0->>'state'='open'
                     AND (payload->0->>'observed_at') <= $3
                     AND NOT (cache_key=ANY($4::text[]))
                   RETURNING cache_key""",
                prefix + "%", _marker(repo,kind), started,
                [entry["key"] for entry in projection],
            )
            await conn.execute(
                """INSERT INTO public.factory_state_kv
                   (cache_key,payload,fetched_at,expires_at,updated_at)
                   VALUES ($1,'[]'::jsonb,now(),'2100-01-01'::timestamptz,now())
                   ON CONFLICT(cache_key) DO UPDATE SET
                     fetched_at=now(),updated_at=now()""",
                _marker(repo,kind),
            )
            changed = [*updated, *removed]
            for row in changed:
                number = int(row["cache_key"].split(":")[-1])
                await conn.execute(
                    """INSERT INTO public.factory_state_events
                       (source,event_type,subject_type,subject_number,detail)
                       VALUES ('github-reconciliation','target_reconciled',$1,$2,
                        jsonb_build_object('target',$3::text))""",
                    kind, number, row["cache_key"],
                )
            return len(updated), len(removed)
    finally:
        await conn.close()


def reconcile_snapshot(repo: str, kind: str, items: list[dict[str, Any]], started: str) -> None:
    if not enabled():
        return
    try:
        updated, removed = asyncio.run(_snapshot(repo, kind, items, started))
        print(f"[factory-projection] reconciled {kind}: {updated} updated, {removed} closed", file=sys.stderr)
    except Exception as exc:
        print(f"[factory-projection] reconciliation unavailable ({type(exc).__name__})", file=sys.stderr)


async def _ingest_event(repo: str, event_id: str, event: dict[str, Any]) -> bool:
    import asyncpg

    record = normalize_event(event)
    if record is None:
        return False
    kind, number, item, state = record
    prefix = _prefix(repo, kind)
    source_updated_at = str(item.get("updatedAt") or "")
    value = json.dumps([{
        "item": item, "state": state, "source_updated_at": source_updated_at,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }])
    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    try:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", prefix)
            row = await conn.fetchrow(
                """INSERT INTO public.factory_state_kv
                     (cache_key,payload,fetched_at,expires_at,updated_at)
                   VALUES ($1,$2::jsonb,now(),'2100-01-01'::timestamptz,now())
                   ON CONFLICT(cache_key) DO UPDATE SET
                     payload=EXCLUDED.payload,updated_at=now()
                   WHERE (factory_state_kv.payload->0->>'source_updated_at')
                         <= (EXCLUDED.payload->0->>'source_updated_at')
                     AND (factory_state_kv.payload->0->'item'
                          IS DISTINCT FROM EXCLUDED.payload->0->'item'
                          OR factory_state_kv.payload->0->>'state' !=
                             EXCLUDED.payload->0->>'state')
                   RETURNING cache_key""",
                _target_key(repo,kind,number), value,
            )
            if row is None:
                return False
            await conn.execute(
                """INSERT INTO public.factory_state_events
                   (source,event_type,subject_type,subject_number,detail)
                   VALUES ('github-webhook','target_changed',$1,$2,
                      jsonb_build_object('event_id',$3::text,'action',$4::text,
                                         'state',$5::text))""",
                kind, number, event_id, str(event.get("action") or ""), state,
            )
            return True
    finally:
        await conn.close()


def ingest_event(repo: str, event_id: str, event: dict[str, Any]) -> bool:
    if not enabled():
        raise RuntimeError("event ingestion requires trusted Neon credentials")
    return asyncio.run(_ingest_event(repo, event_id, event))


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest"])
    parser.add_argument("--file", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    with open(args.file, encoding="utf-8") as stream:
        event = json.load(stream)
    changed = ingest_event(args.repo, args.event_id, event)
    print(f"[factory-projection] target event applied={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
