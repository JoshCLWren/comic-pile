"""Temporary production-runtime Upstash REST latency probe (issue #2216).

REMOVE AFTER MEASUREMENT. This module exists so a Vercel function can time
``KV_REST_API_URL`` / ``KV_REST_API_TOKEN`` from real process env, where
Sensitive values are available. It never logs or returns credentials.

``REDIS_URL`` and ``KV_URL`` are ignored (RESP / local path).
"""

from __future__ import annotations

import os
import secrets
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.services.errors import InvalidRequestError, NotFoundError

PROBE_HEADER_NAME = "X-Cache-Latency-Probe"
TEMPORARY_PROBE_TOKEN = "comic-pile-2216-cache-latency-probe"
BENCH_KV_KEY = "comic_pile_cache_latency_bench_key_v1"
DEFAULT_ITERATIONS = 30
DEFAULT_WARMUPS = 3
PLACEHOLDERS = frozenset({"", "[SENSITIVE]", "<redacted>", "redacted", "undefined", "null"})


@dataclass(frozen=True, slots=True)
class CacheLatencyProbeResult:
    """Redacted Upstash REST GET distribution from this process.

    Attributes:
        measured_from: Vercel region label, or ``unknown``.
        vercel_env: ``VERCEL_ENV`` value when present.
        samples: Successful GET count.
        p50_ms: Median latency in milliseconds.
        p95_ms: 95th-percentile latency in milliseconds.
        min_ms: Fastest successful sample.
        max_ms: Slowest successful sample.
        mean_ms: Mean of successful samples.
        quota_blocked: Whether any sample returned HTTP 429.
        status: ``ok``, ``quota_blocked``, or ``no_samples``.
    """

    measured_from: str
    vercel_env: str
    samples: int
    p50_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None
    mean_ms: float | None
    quota_blocked: bool
    status: str


def _usable(value: str | None) -> str | None:
    """Return a stripped secret if it is not a placeholder.

    Args:
        value: Candidate environment value.

    Returns:
        The stripped value, or ``None``.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped.lower() in PLACEHOLDERS or stripped == "[SENSITIVE]":
        return None
    return stripped


def resolve_kv_rest_url() -> str | None:
    """Return the Upstash REST URL from KV aliases only.

    Returns:
        ``KV_REST_API_URL``, else native Upstash REST URL, else ``None``.
        Never reads ``REDIS_URL`` or ``KV_URL``.
    """
    return _usable(os.environ.get("KV_REST_API_URL")) or _usable(
        os.environ.get("UPSTASH_REDIS_REST_URL")
    )


def resolve_kv_rest_token() -> str | None:
    """Return the preferred Upstash REST token from KV aliases.

    Returns:
        Read-write ``KV_REST_API_TOKEN``, else the GET-only token, else the
        native Upstash token, else ``None``.
    """
    return (
        _usable(os.environ.get("KV_REST_API_TOKEN"))
        or _usable(os.environ.get("KV_REST_API_READ_ONLY_TOKEN"))
        or _usable(os.environ.get("UPSTASH_REDIS_REST_TOKEN"))
    )


def probe_is_enabled() -> bool:
    """Return whether the temporary probe endpoint should answer.

    Returns:
        ``True`` when explicitly enabled or when running on Vercel
        ``preview`` / ``production``. Ordinary local processes stay dark.
    """
    flag = os.getenv("CACHE_LATENCY_PROBE_ENABLED", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return os.getenv("VERCEL_ENV", "").strip().lower() in {"preview", "production"}


def authorize_probe_header(provided: str | None) -> None:
    """Reject callers that omit the temporary shared probe token.

    Args:
        provided: Value of ``X-Cache-Latency-Probe``.

    Raises:
        NotFoundError: When the probe is disabled or the header does not match.
    """
    if not probe_is_enabled():
        raise NotFoundError("Not Found")
    expected = TEMPORARY_PROBE_TOKEN.encode("utf-8")
    actual = (provided or "").encode("utf-8")
    if len(actual) != len(expected):
        raise NotFoundError("Not Found")
    if not secrets.compare_digest(actual, expected):
        raise NotFoundError("Not Found")


def _get_once(url: str, token: str, timeout: float) -> tuple[float, int, str | None]:
    """Time one Upstash REST GET. Returns elapsed_ms, http_status, error."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return 0.0, 0, "invalid_upstash_url"
    started = time.perf_counter()
    request = urllib.request.Request(url, method="GET")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    request.add_header("User-Agent", "comic-pile-cache-latency-probe/1")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return elapsed_ms, response.status, None
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, exc.code, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, 0, type(exc).__name__


def measure_upstash_rest_get(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    warmups: int = DEFAULT_WARMUPS,
    timeout: float = 10.0,
) -> CacheLatencyProbeResult:
    """Time Upstash REST GETs using process-env KV REST credentials.

    Args:
        iterations: Recorded samples.
        warmups: Unrecorded warm-up calls.
        timeout: Per-request timeout in seconds.

    Returns:
        Redacted latency summary. Never includes URL, token, or host.

    Raises:
        InvalidRequestError: When KV REST credentials are missing in-process.
    """
    base_url = resolve_kv_rest_url()
    token = resolve_kv_rest_token()
    if base_url is None or token is None:
        raise InvalidRequestError("kv_rest_not_configured")

    encoded_key = urllib.parse.quote(BENCH_KV_KEY, safe="")
    endpoint = f"{base_url.rstrip('/')}/get/{encoded_key}"
    ok_samples: list[float] = []
    quota_blocked = False
    for index in range(-warmups, iterations):
        elapsed_ms, http_status, _error = _get_once(endpoint, token, timeout)
        if http_status == 429:
            quota_blocked = True
            continue
        # 200 is the Upstash REST GET contract (null result is still 200).
        # 404 is counted as a completed hop so a missing bench key still
        # contributes latency instead of emptying the distribution.
        if http_status in {200, 404} and index >= 0:
            ok_samples.append(round(elapsed_ms, 3))

    region = os.getenv("VERCEL_REGION") or "unknown"
    vercel_env = os.getenv("VERCEL_ENV") or "unknown"
    if not ok_samples:
        return CacheLatencyProbeResult(
            measured_from=f"vercel:{region}",
            vercel_env=vercel_env,
            samples=0,
            p50_ms=None,
            p95_ms=None,
            min_ms=None,
            max_ms=None,
            mean_ms=None,
            quota_blocked=quota_blocked,
            status="quota_blocked" if quota_blocked else "no_samples",
        )
    try:
        p95 = statistics.quantiles(ok_samples, n=20)[18]
    except (statistics.StatisticsError, IndexError):
        p95 = max(ok_samples)
    return CacheLatencyProbeResult(
        measured_from=f"vercel:{region}",
        vercel_env=vercel_env,
        samples=len(ok_samples),
        p50_ms=round(statistics.median(ok_samples), 3),
        p95_ms=round(p95, 3),
        min_ms=min(ok_samples),
        max_ms=max(ok_samples),
        mean_ms=round(statistics.fmean(ok_samples), 3),
        quota_blocked=quota_blocked,
        status="ok",
    )
