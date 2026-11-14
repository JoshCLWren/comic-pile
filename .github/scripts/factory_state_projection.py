"""Event-maintained issue/PR projections with periodic GitHub drift repair.

This runs only in trusted Actions jobs. It reads/writes the existing isolated
factory_state KV and event tables; webhook payloads are normalized, not executed.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from factory_state_cache import _dsn

PREFIX = "factory-projection-v1:"
RECONCILE_SECONDS = 1800


class GitHubTargetVerificationError(RuntimeError):
    """A trusted webhook target could not be verified against live GitHub."""


def enabled() -> bool:
    """Return whether a restricted trusted-factory Neon connection is configured.

    Returns:
        True when an on-runner connection file path is set.
    """
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


def canonical_item(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    """Keep only stable discovery fields across REST webhooks and GH CLI.

    GitHub's REST and GraphQL label objects have different metadata and order;
    neither label color nor API identity is factory scheduling state.
    """
    names = sorted({
        label["name"] for label in (item.get("labels") or [])
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    })
    canonical: dict[str, Any] = {
        "number": item["number"],
        "title": item.get("title") or "",
        "body": item.get("body") or "",
        "labels": [{"name": name} for name in names],
        "createdAt": item.get("createdAt") or item.get("created_at") or "",
        "updatedAt": item.get("updatedAt") or item.get("updated_at") or "",
    }
    if kind == "pr":
        mergeable = item.get("mergeable")
        # REST reports bool/null; gh pr list reports an enum/null.
        if mergeable is True:
            mergeable = "MERGEABLE"
        elif mergeable is False:
            mergeable = "CONFLICTING"
        elif isinstance(mergeable, str):
            mergeable = mergeable.upper()
        head = item.get("head") or {}
        base = item.get("base") or {}
        canonical.update({
            "headRefName": item.get("headRefName") or head.get("ref") or "",
            "headRefOid": item.get("headRefOid") or head.get("sha") or "",
            "isDraft": bool(item.get("isDraft", item.get("draft", False))),
            "mergeable": mergeable,
            "mergeStateStatus": str(item.get("mergeStateStatus") or item.get("mergeable_state") or "UNKNOWN").upper(),
            "isCrossRepository": bool(
                item["isCrossRepository"] if "isCrossRepository" in item else
                (head.get("repo") or {}).get("full_name") != (base.get("repo") or {}).get("full_name")
            ),
        })
    return canonical


def normalize_event(event: dict[str, object]) -> tuple[str, int, dict[str, object], str] | None:
    """Normalize GitHub events into the factory queue's discovery fields.

    Args:
        event: GitHub issue or pull request event object.

    Returns:
        Kind, number, normalized record and state, or None for invalid data.
    """
    is_pr = "pull_request" in event
    raw = event.get("pull_request") if is_pr else event.get("issue")
    if not isinstance(raw, dict) or not isinstance(raw.get("number"), int):
        return None
    kind = "pr" if is_pr else "issue"
    item = canonical_item(kind, raw)
    return kind, int(raw["number"]), item, str(raw.get("state") or "open").lower()


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


def projected_json(repo: str, kind: str) -> list[dict[str, object]] | None:
    """Return projected open items only while reconciliation is recent.

    Args:
        repo: GitHub owner/repository.
        kind: Either issue or pr.

    Returns:
        Current open items, or None when discovery must repair a stale snapshot.
    """
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
    started_at = datetime.fromisoformat(started.replace("Z", "+00:00"))
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    projection = [{
        "key": _target_key(repo, kind, int(item["number"])),
        "item": canonical_item(kind, item),
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
                   WHERE (COALESCE(NULLIF(factory_state_kv.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz))
                         <= (COALESCE(NULLIF(EXCLUDED.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz))
                     AND (factory_state_kv.payload->0->'item'
                          IS DISTINCT FROM EXCLUDED.payload->0->'item'
                          OR factory_state_kv.payload->0->>'state' != 'open')
                     AND (
                       (factory_state_kv.payload->0->>'observed_at')::timestamptz <= $2::timestamptz
                       OR COALESCE(NULLIF(factory_state_kv.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz)
                          < COALESCE(NULLIF(EXCLUDED.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz)
                     )
                   RETURNING cache_key""",
                json.dumps(projection), started_at,
            )
            removed = await conn.fetch(
                """UPDATE public.factory_state_kv SET
                     payload=jsonb_set(
                       jsonb_set(payload,'{0,state}','"closed"'::jsonb),
                       '{0,source_updated_at}',to_jsonb($5::text)),
                     updated_at=now()
                   WHERE cache_key LIKE $1
                     AND cache_key != $2
                     AND payload->0->>'state'='open'
                     AND (payload->0->>'observed_at')::timestamptz <= $3::timestamptz
                     AND NOT (cache_key=ANY($4::text[]))
                   RETURNING cache_key""",
                prefix + "%", _marker(repo,kind), started_at,
                [entry["key"] for entry in projection], started,
            )
            await conn.execute(
                """INSERT INTO public.factory_state_kv
                   (cache_key,payload,fetched_at,expires_at,updated_at)
                   VALUES ($1,jsonb_build_array(jsonb_build_object('started_at',$2::text)),
                           now(),'2100-01-01'::timestamptz,now())
                   ON CONFLICT(cache_key) DO UPDATE SET
                     payload=EXCLUDED.payload,
                     fetched_at=now(),updated_at=now()""",
                _marker(repo,kind), started,
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


def reconcile_snapshot(repo: str, kind: str, items: list[dict[str, object]], started: str) -> None:
    """Record one live GitHub inventory to repair missing or closed projections.

    Args:
        repo: GitHub owner/repository.
        kind: Issue or PR.
        items: Results from a live GitHub listing, never cached.
        started: UTC watermark from before the GitHub read.
    """
    if not enabled():
        return
    try:
        updated, removed = asyncio.run(_snapshot(repo, kind, items, started))
        from factory_state_operations import checkpoint
        checkpoint(repo, f"targets:{kind}", started, updated + removed)
        print(f"[factory-projection] reconciled {kind}: {updated} updated, {removed} closed", file=sys.stderr)
    except Exception as exc:
        print(f"[factory-projection] reconciliation unavailable ({type(exc).__name__})", file=sys.stderr)


def _authoritative_event(repo: str, event: dict[str, Any]) -> dict[str, Any]:
    """Read the *one* current GitHub target, ignoring webhook delivery order.

    Args:
        repo: Expected GitHub owner/repository.
        event: Untrusted incoming event identifying the issue or PR.

    Returns:
        An event envelope containing the currently authoritative GitHub item.

    Raises:
        RuntimeError: When the exact target cannot be verified via GitHub.
    """
    kind = "pull_request" if "pull_request" in event else "issue"
    raw = event.get(kind)
    if not isinstance(raw, dict) or type(raw.get("number")) is not int:
        return event
    number = raw["number"]
    path = "pulls" if kind == "pull_request" else "issues"
    response = subprocess.run(
        ["gh", "api", f"repos/{repo}/{path}/{number}"],
        capture_output=True, text=True, check=False, timeout=20,
    )
    if response.returncode:
        # Classify known failures without exposing raw API output in trusted CI logs.
        if "rate limit exceeded" in response.stderr.lower():
            raise GitHubTargetVerificationError(
                f"GitHub API rate limit exceeded while verifying {kind} #{number}"
            )
        raise GitHubTargetVerificationError(f"GitHub could not verify {kind} #{number}")
    try:
        current = json.loads(response.stdout)
    except (TypeError, ValueError) as exc:
        raise GitHubTargetVerificationError(f"Invalid GitHub response for {kind} #{number}") from exc
    if not isinstance(current, dict) or current.get("number") != number:
        raise GitHubTargetVerificationError(f"Unexpected GitHub target identity for {kind} #{number}")
    return {kind: current}


async def _ingest_event(repo: str, event_id: str, event: dict[str, Any]) -> bool:
    """Serialize a one-target GitHub read and its Neon projection write."""
    import asyncpg

    raw = event.get("pull_request") if "pull_request" in event else event.get("issue")
    if not isinstance(raw, dict) or type(raw.get("number")) is not int:
        return False
    kind = "pr" if "pull_request" in event else "issue"
    prefix = _prefix(repo, kind)
    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=35)
    try:
        async with conn.transaction():
            # Move the live read *inside* the same advisory lock as the write.
            # Two equal-timestamp close/reopen events can no longer apply an
            # earlier observation after a later one.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", prefix
            )
            record = normalize_event(_authoritative_event(repo, event))
            if record is None:
                return False
            normalized_kind, number, item, state = record
            if normalized_kind != kind:
                raise ValueError("event kind changed during authoritative lookup")
            source_updated_at = str(item.get("updatedAt") or "")
            value = json.dumps([{
                "item": item, "state": state,
                "source_updated_at": source_updated_at,
                "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }])
            row = await conn.fetchrow(
                """INSERT INTO public.factory_state_kv
                     (cache_key,payload,fetched_at,expires_at,updated_at)
                   SELECT $1,$2::jsonb,now(),'2100-01-01'::timestamptz,now()
                   WHERE NOT EXISTS (
                     SELECT 1 FROM public.factory_state_kv
                      WHERE cache_key=$3
                        AND COALESCE(
                          NULLIF(payload->0->>'started_at','')::timestamptz,
                          fetched_at
                        ) >= COALESCE(
                          NULLIF($2::jsonb->0->>'source_updated_at','')::timestamptz,
                          'epoch'::timestamptz
                        )
                        AND $2::jsonb->0->>'state'='open'
                   )
                   ON CONFLICT(cache_key) DO UPDATE SET
                     payload=EXCLUDED.payload,updated_at=now()
                   WHERE (COALESCE(NULLIF(factory_state_kv.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz))
                         <= (COALESCE(NULLIF(EXCLUDED.payload->0->>'source_updated_at','')::timestamptz, 'epoch'::timestamptz))
                     AND (factory_state_kv.payload->0->'item'
                          IS DISTINCT FROM EXCLUDED.payload->0->'item'
                          OR factory_state_kv.payload->0->>'state' !=
                             EXCLUDED.payload->0->>'state')
                   RETURNING cache_key""",
                _target_key(repo, kind, number), value, _marker(repo, kind),
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


async def _bootstrap_kind(repo: str, kind: str) -> bool:
    """Initialize missing projection inventory once, under a shared DB lock."""
    import asyncpg

    prefix = _prefix(repo, kind)
    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=35)
    try:
        async with conn.transaction():
            # This separate lock serializes first-time full inventories across
            # webhook runners. It does not block single-target webhook writes.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
                prefix + "bootstrap",
            )
            found = await conn.fetchval(
                "SELECT 1 FROM public.factory_state_kv WHERE cache_key=$1",
                _marker(repo, kind),
            )
            if found:
                return False
            if kind == "issue":
                limit = 1000
                command = [
                    "gh", "issue", "list", "--repo", repo, "--state", "open",
                    "--limit", str(limit),
                    "--json", "number,title,body,labels,createdAt,updatedAt",
                ]
            else:
                limit = 500
                command = [
                    "gh", "pr", "list", "--repo", repo, "--state", "open",
                    "--limit", str(limit),
                    "--json",
                    "number,title,body,labels,headRefName,headRefOid,createdAt,"
                    "updatedAt,isDraft,mergeable,mergeStateStatus,isCrossRepository",
                ]
            started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            result = await asyncio.to_thread(
                subprocess.run, command, capture_output=True, text=True,
                timeout=60, check=False,
            )
            if result.returncode:
                raise RuntimeError(f"GitHub {kind} inventory bootstrap failed")
            try:
                items = json.loads(result.stdout)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Invalid GitHub bootstrap inventory") from exc
            if not isinstance(items, list) or len(items) >= limit:
                raise RuntimeError("GitHub bootstrap listing is incomplete")
            await _snapshot(repo, kind, items, started)
            return True
    finally:
        await conn.close()


def bootstrap_missing(repo: str) -> None:
    """Bootstrap each absent issue/PR projection exactly once per repository.

    Args:
        repo: GitHub repository whose open targets require a baseline.

    The advisory locks avoid redundant broad scans on simultaneous webhooks.
    Failures leave the missing marker for a later retry.
    """
    if not enabled():
        return
    for kind in ("issue", "pr"):
        try:
            created = asyncio.run(_bootstrap_kind(repo, kind))
            if created:
                print(f"[factory-projection] initialized {kind} snapshot", file=sys.stderr)
        except Exception as exc:
            print(
                f"[factory-projection] {kind} initialization deferred "
                f"({type(exc).__name__})",
                file=sys.stderr,
            )


def ingest_event(repo: str, event_id: str, event: dict[str, object]) -> bool:
    """Apply one current target through restricted Neon event ingestion.

    Args:
        repo: GitHub repository.
        event_id: Trusted job/delivery identifier.
        event: Original untrusted webhook envelope.

    Returns:
        True if the current target changed.

    Raises:
        RuntimeError: If Neon or live GitHub target verification fails.
    """
    if not enabled():
        raise RuntimeError("event ingestion requires trusted Neon credentials")
    return asyncio.run(_ingest_event(repo, event_id, event))


def main() -> int:
    """Read one trusted GitHub Actions event and ingest its target.

    Returns:
        Zero for a successful ingest run.
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["ingest"])
    parser.add_argument("--file", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()
    with open(args.file, encoding="utf-8") as stream:
        event = json.load(stream)
    try:
        changed = ingest_event(args.repo, args.event_id, event)
    except GitHubTargetVerificationError as exc:
        # Fail closed for the projection: never persist an unverified webhook
        # payload. GitHub read outages are deferred to the periodic authoritative
        # reconciliation; they are not failures of the PR's product checks.
        print(
            f"::warning::Factory target ingest deferred ({exc}); "
            "no unverified projection written. Periodic GitHub reconciliation will repair drift.",
            file=sys.stderr,
        )
        return 0
    bootstrap_missing(args.repo)
    print(f"[factory-projection] target event applied={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
