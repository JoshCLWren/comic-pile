"""Shared Neon snapshot cache for trusted GitHub Actions controller reads.

GitHub remains authoritative for claims, reviews, checks, and merges. This
cache only replaces repeated discovery listings. It never grants ownership.
The database is isolated in the factory_state database with a scoped role.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _dsn() -> str:
    path = os.environ.get("FACTORY_STATE_DSN_FILE", "")
    if not path:
        raise RuntimeError("factory cache is not configured")
    raw = Path(path).read_text(encoding="utf-8").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in ("postgresql", "postgres"):
        raise ValueError("factory state connection must be a Postgres URL")
    if not parsed.hostname or not parsed.username:
        raise ValueError("factory state connection is missing its host or role")
    # Neon's libpq URL can include channel_binding, which asyncpg does not
    # accept. TLS stays required via sslmode=require in the original DSN.
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key != "channel_binding"]
    return urlunsplit(parsed._replace(query=urlencode(query)))


async def _query(sql: str, *args: Any, one: bool = False) -> Any:
    import asyncpg

    conn = await asyncpg.connect(dsn=_dsn(), timeout=8, command_timeout=8)
    try:
        if one:
            return await conn.fetchrow(sql, *args)
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


def _run(sql: str, *args: Any, one: bool = False) -> Any:
    return asyncio.run(_query(sql, *args, one=one))


def _payload(value: Any) -> list[dict[str, Any]] | None:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, list) else None


def _read(key: str) -> tuple[list[dict[str, Any]] | None, bool]:
    row = _run(
        "SELECT payload, expires_at FROM public.factory_state_kv WHERE cache_key=$1",
        key, one=True,
    )
    if row is None:
        return None, False
    data = _payload(row["payload"])
    fresh = bool(data is not None and row["expires_at"] > datetime.now(timezone.utc))
    return data, fresh


def _claim(key: str, owner: str) -> bool:
    row = _run(
        """
        INSERT INTO public.factory_state_kv
          (cache_key, payload, fetched_at, expires_at, refresh_owner, refresh_until)
        VALUES ($1, '[]'::jsonb, to_timestamp(0), to_timestamp(0),
                $2, now() + interval '75 seconds')
        ON CONFLICT(cache_key) DO UPDATE
          SET refresh_owner=EXCLUDED.refresh_owner,
              refresh_until=EXCLUDED.refresh_until
          WHERE factory_state_kv.expires_at <= now()
            AND (factory_state_kv.refresh_until IS NULL
                 OR factory_state_kv.refresh_until < now())
        RETURNING cache_key
        """,
        key, owner, one=True,
    )
    return row is not None


def _publish(key: str, owner: str, data: list[dict[str, Any]], ttl_seconds: int) -> None:
    # A lock that expired or changed owner may not publish an older snapshot.
    _run(
        """
        WITH refreshed AS (
            UPDATE public.factory_state_kv
               SET payload=$3::jsonb, fetched_at=now(),
                   expires_at=now() + $4::int * interval '1 second',
                   refresh_owner=NULL, refresh_until=NULL, updated_at=now()
             WHERE cache_key=$1 AND refresh_owner=$2
             RETURNING cache_key
        )
        INSERT INTO public.factory_state_events (source, event_type, detail)
        SELECT 'github-actions', 'cache_refresh',
               jsonb_build_object('key', cache_key, 'records', $5::int)
          FROM refreshed
        """,
        key, owner, json.dumps(data), ttl_seconds, len(data),
    )



def _refresh_without_rewrite(key: str, owner: str, ttl_seconds: int, records: int) -> None:
    """Extend freshness without retransmitting or rewriting an unchanged TOAST value."""
    _run(
        """
        WITH refreshed AS (
            UPDATE public.factory_state_kv
               SET fetched_at=now(), expires_at=now() + $3::int * interval '1 second',
                   refresh_owner=NULL, refresh_until=NULL, updated_at=now()
             WHERE cache_key=$1 AND refresh_owner=$2
             RETURNING cache_key
        )
        INSERT INTO public.factory_state_events (source, event_type, detail)
        SELECT 'github-actions', 'cache_refresh',
               jsonb_build_object('key', cache_key, 'records', $4::int, 'unchanged', true)
          FROM refreshed
        """,
        key, owner, ttl_seconds, records,
    )


def _prune_expired_github_cache(batch_size: int = 200) -> int:
    """Delete only long-expired, non-authoritative GitHub GET snapshots.

    Never prune projections, comment registries, worker/provider state or leases.
    An in-progress refresh also remains protected. Batches avoid long locks.
    """
    if not 1 <= batch_size <= 1000:
        raise ValueError("invalid cache cleanup batch size")
    row = _run(
        """
        WITH stale AS (
            SELECT cache_key FROM public.factory_state_kv
             WHERE cache_key LIKE 'factory-github-get-v1:%'
               AND expires_at < now() - interval '30 minutes'
               AND (refresh_until IS NULL OR refresh_until < now())
             ORDER BY expires_at
             LIMIT $1
        ), removed AS (
            DELETE FROM public.factory_state_kv AS cache
             USING stale
             WHERE cache.cache_key = stale.cache_key
               AND cache.expires_at < now() - interval '30 minutes'
               AND (cache.refresh_until IS NULL OR cache.refresh_until < now())
             RETURNING cache.cache_key
        )
        SELECT count(*) AS deleted FROM removed
        """,
        batch_size, one=True,
    )
    return int(row["deleted"])


def _release(key: str, owner: str) -> None:
    _run(
        """
        UPDATE public.factory_state_kv
           SET refresh_owner=NULL, refresh_until=NULL
         WHERE cache_key=$1 AND refresh_owner=$2
        """,
        key, owner,
    )


def _recent_contended(key: str, max_stale_seconds: int) -> list[dict[str, Any]] | None:
    """Share a bounded expired discovery result only while its refresh is owned."""
    row = _run(
        """
        SELECT payload FROM public.factory_state_kv
        WHERE cache_key=$1 AND refresh_until > now()
          AND expires_at > now() - $2::int * interval '1 second'
        """,
        key, max_stale_seconds, one=True,
    )
    return _payload(row["payload"]) if row is not None else None


def cached_json(
    key: str,
    fetch: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    *,
    ttl_seconds: int = 45,
) -> list[dict[str, Any]]:
    """Get a recent shared snapshot, or fetch once under a short DB refresh lease.

    The caller's fetch function is authoritative, never a model. On database
    errors, use the original live GitHub path. A concurrent cold cache fill
    waits briefly; if it cannot observe a fresh snapshot it fetches live.
    """
    if not 1 <= ttl_seconds <= 3600:
        raise ValueError("invalid factory cache TTL")
    if not os.environ.get("FACTORY_STATE_DSN_FILE"):
        return fetch([])
    try:
        previous, fresh = _read(key)
    except Exception as error:
        print(f"[factory-state] cache read unavailable, fetching GitHub live ({type(error).__name__})", file=sys.stderr)
        return fetch([])
    if fresh:
        print(f"[factory-state] shared cache hit for {key}", file=sys.stderr)
        return previous or []

    owner = f"{os.environ.get('GITHUB_RUN_ID', 'local')}-{uuid.uuid4().hex}"
    try:
        claimed = _claim(key, owner)
    except Exception as error:
        print(f"[factory-state] cache claim unavailable, fetching GitHub live ({type(error).__name__})", file=sys.stderr)
        return fetch(previous or [])

    if not claimed:
        # Another trusted runner holds the refresh lease. Safe discovery
        # callers may share a briefly stale record while it is actively
        # refreshed; no ownership, checks, or merge authorization uses this.
        # Never serve an expired cold/invalid cache or an abandoned lease.
        if previous is not None:
            try:
                shared = _recent_contended(key, min(ttl_seconds, 120))
            except Exception:
                shared = None
            if shared is not None:
                print(f"[factory-state] shared in-flight refresh for {key}", file=sys.stderr)
                return shared

        # A cold cache has no safe stale result. Give the single refresh
        # owner time to publish rather than launching competing GitHub scans.
        # Contenders wait here; a sufficiently long bounded wait allows them
        # to observe the winner's published result instead of starting duplicate
        # live fetches. On a genuine outage, retain live fallback.
        for _ in range(120):
            time.sleep(1)
            try:
                data, fresh = _read(key)
            except Exception:
                break
            if fresh:
                return data or []
        # If we had previous cache data, prefer it over a duplicate live fetch
        # to avoid contenders repeating the winner's GitHub discovery work.
        if previous is not None:
            return previous
        print(f"[factory-state] refresh wait exceeded for {key}, fetching GitHub live", file=sys.stderr)
        return fetch(previous or [])

    try:
        result = fetch(previous or [])
        if not isinstance(result, list):
            raise ValueError(f"invalid GitHub discovery payload for {key}")
    except BaseException:
        try:
            _release(key, owner)
        except Exception:
            pass
        raise

    unchanged = previous is not None and result == previous
    try:
        if unchanged:
            _refresh_without_rewrite(key, owner, ttl_seconds, len(result))
        else:
            _publish(key, owner, result, ttl_seconds)
    except Exception as error:
        print(f"[factory-state] cache publication unavailable ({type(error).__name__})", file=sys.stderr)
        try:
            _release(key, owner)
        except Exception:
            pass
    else:
        label = "extended unchanged" if unchanged else "refreshed"
        print(f"[factory-state] {label} {key}: {len(result)} records", file=sys.stderr)
    return result


def incremental_comments(
    previous: list[dict[str, Any]],
    fetch_since: Callable[[str | None], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Fetch changed issue comments since the latest timestamp, deduped by ID.

    Initial fill is a full scan exactly once. Edits to older comments are
    included by GitHub's updated_at filter. The minute overlap accounts for
    second-precision timestamps and concurrent updates.
    """
    latest = None
    for comment in previous:
        stamp = comment.get("updated_at") or comment.get("created_at")
        if not isinstance(stamp, str):
            continue
        try:
            candidate = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or candidate > latest:
            latest = candidate
    since = None
    if latest is not None:
        from datetime import timedelta
        since = (latest - timedelta(minutes=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    changes = fetch_since(since)
    if not isinstance(changes, list):
        raise ValueError("GitHub returned a non-list comment page")
    by_id = {comment["id"]: comment for comment in previous if isinstance(comment, dict) and "id" in comment}
    for comment in changes:
        if not isinstance(comment, dict) or "id" not in comment:
            raise ValueError("GitHub returned a malformed issue comment")
        by_id[comment["id"]] = comment
    return sorted(by_id.values(), key=lambda comment: (comment.get("created_at") or "", comment["id"]))


def main(argv: list[str]) -> int:
    if argv != ["prune-expired"]:
        print("usage: factory_state_cache.py prune-expired", file=sys.stderr)
        return 2
    if not os.environ.get("FACTORY_STATE_DSN_FILE"):
        raise RuntimeError("cache cleanup requires trusted Neon credentials")
    deleted = 0
    for _ in range(5):
        count = _prune_expired_github_cache()
        deleted += count
        if count < 200:
            break
    print(f"[factory-state] pruned {deleted} expired GitHub GET cache rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
