"""Endpoint-aware ComicVine provider client with persistent cache and resource throttling."""

from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from filelock import FileLock

COMICVINE_BASE_URL = "https://comicvine.gamespot.com/api"
DEFAULT_REQUESTS_PER_HOUR = 195
DEFAULT_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS = 1.05
COLLECTION_PAGE_LIMIT = 100
DEEP_ISSUE_FIELDS = (
    "id",
    "name",
    "issue_number",
    "cover_date",
    "store_date",
    "image",
    "volume",
    "person_credits",
    "character_credits",
    "team_credits",
    "story_arc_credits",
    "date_last_updated",
)


class ComicVineError(RuntimeError):
    """Base error raised for provider failures."""


class ComicVineRateLimitError(ComicVineError):
    """Raised when one ComicVine resource is temporarily unavailable."""

    def __init__(
        self,
        message: str,
        *,
        resource: str | None = None,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.resource = resource
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class ComicVineResponse:
    """One decoded provider response plus cache provenance."""

    payload: dict[str, object]
    from_cache: bool
    cache_key: str


def _retry_after_seconds(headers: object, *, now: float | None = None) -> int | None:
    """Parse Retry-After as delta-seconds or an HTTP date."""
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    raw = getter("Retry-After")
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    try:
        return max(0, int(value))
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    current = time.time() if now is None else now
    return max(0, math.ceil(parsed.timestamp() - current))


class PersistentEndpointLimiter:
    """Persist request timestamps per endpoint so restarts retain the rolling budget."""

    def __init__(
        self,
        path: str | Path,
        *,
        requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Configure a persistent rolling-hour limiter."""
        if requests_per_hour <= 0:
            raise ValueError("requests_per_hour must be positive")
        self.path = Path(path)
        self.requests_per_hour = requests_per_hour
        self._clock = clock
        self._lock = FileLock(f"{self.path}.lock")

    def _read(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, list[float]] = {}
        for endpoint, timestamps in raw.items():
            if isinstance(endpoint, str) and isinstance(timestamps, list):
                result[endpoint] = [
                    float(value) for value in timestamps if isinstance(value, int | float)
                ]
        return result

    def _write(self, ledger: Mapping[str, list[float]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)

    def acquire(self, endpoint: str) -> None:
        """Record one request or raise when the rolling endpoint budget is exhausted."""
        now = float(self._clock())
        cutoff = now - 3600
        with self._lock:
            ledger = self._read()
            recent = [stamp for stamp in ledger.get(endpoint, []) if stamp > cutoff]
            if len(recent) >= self.requests_per_hour:
                raise ComicVineRateLimitError(
                    f"ComicVine local rate budget exhausted for resource {endpoint!r}",
                    resource=endpoint,
                )
            recent.append(now)
            ledger[endpoint] = recent
            self._write(ledger)


class ComicVineClient:
    """Fetch ComicVine resources with caching and resource-specific throttle state."""

    def __init__(
        self,
        api_key: str,
        cache_dir: str | Path,
        *,
        requests_per_hour: int | None = None,
        minimum_live_request_interval_seconds: float = (
            DEFAULT_MINIMUM_LIVE_REQUEST_INTERVAL_SECONDS
        ),
        base_url: str = COMICVINE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Configure the provider client."""
        if not api_key.strip():
            raise ValueError("api_key is required")
        if requests_per_hour is not None and requests_per_hour <= 0:
            raise ValueError("requests_per_hour must be positive when provided")
        if minimum_live_request_interval_seconds < 0:
            raise ValueError("minimum_live_request_interval_seconds must be non-negative")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.minimum_live_request_interval_seconds = minimum_live_request_interval_seconds
        self.limiter = (
            PersistentEndpointLimiter(
                self.cache_dir / "request-ledger.json",
                requests_per_hour=requests_per_hour,
            )
            if requests_per_hour is not None
            else None
        )
        self._live_request_lock = asyncio.Lock()
        self._last_live_request_started_at: float | None = None
        self._provider_limits_path = self.cache_dir / "provider-rate-limits.json"
        self._provider_limits_lock = FileLock(f"{self._provider_limits_path}.lock")
        self._blocked_resources: dict[str, float | None] = self._read_provider_limits()

    @staticmethod
    def _cache_key(endpoint: str, params: Mapping[str, object]) -> str:
        safe_params = {key: value for key, value in params.items() if key != "api_key"}
        encoded = json.dumps([endpoint, safe_params], sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{endpoint}-{digest}"

    def _cache_path(self, cache_key: str) -> Path:
        return self.cache_dir / "responses" / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, object] | None:
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_cache(self, cache_key: str, payload: Mapping[str, object]) -> None:
        path = self._cache_path(cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temp.replace(path)

    def _read_provider_limits(self) -> dict[str, float | None]:
        """Load only unexpired Retry-After deadlines from previous runs."""
        if not self._provider_limits_path.exists():
            return {}
        try:
            raw = json.loads(self._provider_limits_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        now = time.time()
        result: dict[str, float | None] = {}
        for resource, deadline in raw.items():
            if (
                isinstance(resource, str)
                and isinstance(deadline, int | float)
                and float(deadline) > now
            ):
                result[resource] = float(deadline)
        return result

    def _write_provider_limits(self) -> None:
        """Persist finite provider Retry-After deadlines across process restarts."""
        now = time.time()
        payload = {
            resource: deadline
            for resource, deadline in self._blocked_resources.items()
            if deadline is not None and deadline > now
        }
        self._provider_limits_path.parent.mkdir(parents=True, exist_ok=True)
        with self._provider_limits_lock:
            temp = self._provider_limits_path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            temp.replace(self._provider_limits_path)

    def _block_resource(self, resource: str, retry_after_seconds: int | None) -> None:
        """Block one resource, persisting the deadline when ComicVine supplied one."""
        if retry_after_seconds is None:
            self._blocked_resources[resource] = None
        else:
            self._blocked_resources[resource] = time.time() + retry_after_seconds
        self._write_provider_limits()

    def _resource_block(self, resource: str) -> tuple[bool, int | None]:
        """Return current block state and remaining Retry-After seconds for one resource."""
        if resource not in self._blocked_resources:
            return False, None
        deadline = self._blocked_resources[resource]
        if deadline is None:
            return True, None
        remaining = math.ceil(deadline - time.time())
        if remaining > 0:
            return True, remaining
        del self._blocked_resources[resource]
        self._write_provider_limits()
        return False, None

    async def _pace_live_request(self) -> None:
        """Space uncached live request starts to avoid provider velocity bursts."""
        interval = self.minimum_live_request_interval_seconds
        if interval <= 0:
            return
        async with self._live_request_lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._last_live_request_started_at is not None:
                delay = self._last_live_request_started_at + interval - now
                if delay > 0:
                    await asyncio.sleep(delay)
            self._last_live_request_started_at = loop.time()

    def _request_sync(self, endpoint: str, params: Mapping[str, object]) -> dict[str, object]:
        query = {
            **params,
            "api_key": self.api_key,
            "format": "json",
        }
        url = f"{self.base_url}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, headers={"User-Agent": "ComicPile/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in {420, 429}:
                resource = endpoint.lstrip("/").split("/", 1)[0]
                retry_after = _retry_after_seconds(exc.headers)
                suffix = (
                    f"; Retry-After={retry_after}s" if retry_after is not None else ""
                )
                raise ComicVineRateLimitError(
                    f"ComicVine returned HTTP {exc.code} for resource {resource!r}{suffix}",
                    resource=resource,
                    status_code=exc.code,
                    retry_after_seconds=retry_after,
                ) from exc
            raise ComicVineError(f"ComicVine HTTP {exc.code} for {endpoint}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ComicVineError(f"ComicVine request failed for {endpoint}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise ComicVineError(f"ComicVine returned a non-object response for {endpoint}")
        status_code = decoded.get("status_code")
        if status_code not in (None, 1):
            raise ComicVineError(
                f"ComicVine API error for {endpoint}: {decoded.get('error', status_code)!r}"
            )
        return decoded

    async def request(
        self,
        endpoint_bucket: str,
        endpoint: str,
        params: Mapping[str, object],
        *,
        refresh: bool = False,
    ) -> ComicVineResponse:
        """Fetch one provider resource, respecting only that resource's throttle state."""
        cache_key = self._cache_key(endpoint, params)
        if not refresh:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return ComicVineResponse(cached, True, cache_key)

        blocked, retry_after = self._resource_block(endpoint_bucket)
        if blocked:
            suffix = f" for another {retry_after}s" if retry_after is not None else ""
            raise ComicVineRateLimitError(
                f"ComicVine resource {endpoint_bucket!r} is blocked for this run{suffix}",
                resource=endpoint_bucket,
                retry_after_seconds=retry_after,
            )

        await self._pace_live_request()
        if self.limiter is not None:
            self.limiter.acquire(endpoint_bucket)
        try:
            payload = await asyncio.to_thread(self._request_sync, endpoint, params)
        except ComicVineRateLimitError as exc:
            retry_after = exc.retry_after_seconds
            self._block_resource(endpoint_bucket, retry_after)
            suffix = f"; Retry-After={retry_after}s" if retry_after is not None else ""
            raise ComicVineRateLimitError(
                f"ComicVine returned HTTP {exc.status_code or 'rate limit'} "
                f"for resource {endpoint_bucket!r}{suffix}",
                resource=endpoint_bucket,
                status_code=exc.status_code,
                retry_after_seconds=retry_after,
            ) from exc
        self._write_cache(cache_key, payload)
        return ComicVineResponse(payload, False, cache_key)

    async def fetch_volume(self, volume_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Fetch one volume resource by ComicVine ID."""
        return await self.request("volume", f"volume/4050-{volume_id}", {}, refresh=refresh)

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Deep-hydrate one issue using the supported singular relationship fields."""
        return await self.request(
            "issue",
            f"issue/4000-{issue_id}",
            {"field_list": ",".join(DEEP_ISSUE_FIELDS)},
            refresh=refresh,
        )

    async def fetch_story_arc(self, arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        """Fetch one story arc without interpreting returned issue-array order as reading order."""
        return await self.request("story_arc", f"story_arc/4045-{arc_id}", {}, refresh=refresh)

    async def fetch_volume_issues(
        self,
        volume_id: int,
        *,
        refresh: bool = False,
    ) -> list[dict[str, object]]:
        """Fetch a complete volume issue roster using the documented 100-row page maximum."""
        rows: list[dict[str, object]] = []
        offset = 0
        while True:
            response = await self.request(
                "issues",
                "issues",
                {
                    "filter": f"volume:{volume_id}",
                    "limit": COLLECTION_PAGE_LIMIT,
                    "offset": offset,
                },
                refresh=refresh,
            )
            results = response.payload.get("results")
            if not isinstance(results, list):
                raise ComicVineError("ComicVine /issues response did not contain a results list")
            page_rows = [row for row in results if isinstance(row, dict)]
            for row in page_rows:
                volume = row.get("volume")
                if isinstance(volume, dict) and volume.get("id") not in (None, volume_id):
                    raise ComicVineError(
                        "ComicVine /issues ignored the requested volume filter; refusing mixed data"
                    )
            rows.extend(page_rows)
            page_count = len(page_rows)
            total = response.payload.get("number_of_total_results")
            if isinstance(total, int) and len(rows) >= total:
                break
            if page_count < COLLECTION_PAGE_LIMIT:
                break
            offset += page_count
        return rows
