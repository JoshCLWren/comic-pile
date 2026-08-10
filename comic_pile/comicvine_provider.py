"""Endpoint-aware ComicVine provider client with persistent cache and rate limiting."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

COMICVINE_BASE_URL = "https://comicvine.gamespot.com/api"
DEFAULT_REQUESTS_PER_HOUR = 180
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
    """Raised when local or provider rate limiting prevents a request."""


@dataclass(frozen=True)
class ComicVineResponse:
    """One decoded provider response plus cache provenance."""

    payload: dict[str, object]
    from_cache: bool
    cache_key: str


class PersistentEndpointLimiter:
    """Persist request timestamps per endpoint so restarts retain the rolling budget."""

    def __init__(
        self,
        path: str | Path,
        *,
        requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR,
        clock: callable = time.time,
    ) -> None:
        """Configure a persistent rolling-hour limiter.

        Args:
            path: JSON ledger path.
            requests_per_hour: Maximum requests per endpoint in one rolling hour.
            clock: Time source used by tests and production.
        """
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
                result[endpoint] = [float(value) for value in timestamps if isinstance(value, int | float)]
        return result

    def _write(self, ledger: Mapping[str, list[float]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        temp.replace(self.path)

    def acquire(self, endpoint: str) -> None:
        """Record one request or raise when the rolling endpoint budget is exhausted.

        Args:
            endpoint: Stable endpoint bucket such as ``issue`` or ``issues``.

        Raises:
            ComicVineRateLimitError: When the endpoint has exhausted its rolling-hour budget.
        """
        now = float(self._clock())
        cutoff = now - 3600
        with self._lock:
            ledger = self._read()
            recent = [stamp for stamp in ledger.get(endpoint, []) if stamp > cutoff]
            if len(recent) >= self.requests_per_hour:
                raise ComicVineRateLimitError(
                    f"ComicVine local rate budget exhausted for endpoint {endpoint!r}"
                )
            recent.append(now)
            ledger[endpoint] = recent
            self._write(ledger)


class ComicVineClient:
    """Fetch ComicVine resources with endpoint-specific contracts and resumable caching."""

    def __init__(
        self,
        api_key: str,
        cache_dir: str | Path,
        *,
        requests_per_hour: int = DEFAULT_REQUESTS_PER_HOUR,
        base_url: str = COMICVINE_BASE_URL,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Configure the provider client.

        Args:
            api_key: ComicVine API key. It is never included in cache keys or persisted payload metadata.
            cache_dir: Directory for raw successful response cache and request ledger.
            requests_per_hour: Conservative rolling-hour budget per endpoint path.
            base_url: Provider API base URL.
            timeout_seconds: Network timeout per request.
        """
        if not api_key.strip():
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.limiter = PersistentEndpointLimiter(
            self.cache_dir / "request-ledger.json",
            requests_per_hour=requests_per_hour,
        )

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
            if exc.code == 429:
                raise ComicVineRateLimitError("ComicVine returned HTTP 429") from exc
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
        """Fetch one provider resource, reusing a persisted successful response by default.

        Args:
            endpoint_bucket: Stable rate-limit bucket for the provider path.
            endpoint: Relative API path.
            params: Provider request parameters excluding credentials and output format.
            refresh: Force a live request instead of using a cached successful payload.

        Returns:
            Decoded provider payload with cache provenance.
        """
        cache_key = self._cache_key(endpoint, params)
        if not refresh:
            cached = self._read_cache(cache_key)
            if cached is not None:
                return ComicVineResponse(cached, True, cache_key)
        self.limiter.acquire(endpoint_bucket)
        payload = await asyncio.to_thread(self._request_sync, endpoint, params)
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
        """Fetch a complete volume issue roster using the documented 100-row page maximum.

        Args:
            volume_id: ComicVine volume ID.
            refresh: Force live requests for every page.

        Returns:
            Ordered provider rows across all pages.

        Raises:
            ComicVineError: When pagination metadata is inconsistent or a returned row belongs to
                a different volume, which indicates that the provider ignored the collection filter.
        """
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
