"""Disposable in-region latency probe for cache backends.

Deploy on throwaway preview branches only; never wire into the real application.

Credentials arrive per-request via headers and are never logged or stored:

- ``X-Bench-Redis-Url``: RESP URL (redis:// or rediss://)
- ``X-Bench-Upstash-Url`` / ``X-Bench-Upstash-Token``: REST credentials

Query parameters:
- ``kind``: ``redis`` (default) or ``upstash``
- ``n``: warm samples (default 100, max 500)
"""

import json
import statistics
import time
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _summarize(timings: list[float]) -> dict[str, float]:
    ordered = sorted(timings)
    return {
        "min_ms": round(ordered[0], 2),
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[int(len(ordered) * 0.95)], 2),
        "max_ms": round(ordered[-1], 2),
    }


async def _time_n(operation: Callable[[], Awaitable[object]], n: int) -> list[float]:
    out: list[float] = []
    for _ in range(n):
        started = time.perf_counter()
        await operation()
        out.append((time.perf_counter() - started) * 1000)
    return out


@app.get("/api/bench")
async def bench(
    kind: str = Query("redis"),
    n: int = Query(100, ge=1, le=500),
    x_bench_redis_url: str | None = Header(default=None),
    x_bench_upstash_url: str | None = Header(default=None),
    x_bench_upstash_token: str | None = Header(default=None),
) -> JSONResponse:
    """Run warm-command latency probes from this function's vantage."""
    if kind == "upstash":
        if not x_bench_upstash_url or not x_bench_upstash_token:
            return JSONResponse(status_code=400, content={"error": "missing upstash headers"})
        headers = {"Authorization": f"Bearer {x_bench_upstash_token}"}
        base = x_bench_upstash_url.rstrip("/")
        statuses: set[int] = set()

        async def rest_get() -> None:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{base}/get/benchmark-probe-key", headers=headers)
                statuses.add(response.status_code)

        timings = await _time_n(rest_get, n)
        return JSONResponse(
            content={"kind": kind, "samples": n, "statuses": sorted(statuses), **_summarize(timings)}
        )

    if not x_bench_redis_url:
        return JSONResponse(status_code=400, content={"error": "missing redis header"})

    import redis.asyncio as aioredis

    client = aioredis.from_url(
        x_bench_redis_url,
        decode_responses=True,
        socket_connect_timeout=6,
        socket_timeout=6,
    )
    try:
        await client.set("benchmark-probe-key", "x" * 512)
        get_timings = await _time_n(
            lambda: client.get("benchmark-probe-key"),
            n,
        )
        set_timings = await _time_n(
            lambda: client.set("benchmark-probe-key", "x" * 512),
            max(n // 4, 1),
        )
    finally:
        await client.aclose()

    return JSONResponse(
        content=json.loads(
            json.dumps(
                {
                    "kind": kind,
                    "get": {"samples": n, **_summarize(get_timings)},
                    "set": {"samples": len(set_timings), **_summarize(set_timings)},
                }
            )
        )
    )
