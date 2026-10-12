"""Edge-cacheable remote comic cover image delivery.

ComicPile stores canonical third-party cover-art URLs (typically ComicVine
uploads) in its database. Rendering those URLs directly couples the browser to
the upstream host for latency, availability, cache behavior, and format. This
service is the single sanctioned transformation point between canonical source
URLs and the bytes the browser receives:

- only explicitly allowlisted upstream hosts are fetched;
- resolved addresses must be publicly routable (SSRF protection);
- payloads are size-capped and content-type-checked;
- images are downscaled to bounded width buckets and re-encoded as WebP when a
  transcoder is available, falling back to validated passthrough bytes;
- responses are marked immutable and shared-cacheable so Vercel's CDN serves
  repeat requests from the edge instead of refetching the upstream host.
"""

import asyncio
import hashlib
import io
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.config import get_image_delivery_settings
from app.repositories.image_optimization_cache_repository import (
    ImageOptimizationCacheRepository,
)

logger = logging.getLogger(__name__)

SUPPORTED_WIDTHS = (96, 240, 480, 720)

_MAX_SOURCE_URL_LENGTH = 2048

_ALLOWED_SCHEMES = ("http", "https")

_UPSTREAM_USER_AGENT = "ComicPileImageOptimizer/1.0"

# ComicVine publishes cover renditions through ``static*.comicvine.com``. Those
# names are only aliases: the CDN answers every request with a 301 to the same
# path under the canonical origin below, which is where the bytes actually live.
# The optimizer deliberately refuses to follow redirects, because an unvalidated
# ``Location`` would walk straight past the allowlist and the SSRF guard, so the
# alias is resolved up front instead. Only the host and the fixed path prefix are
# substituted; the requested rendition path and query are preserved verbatim.
_COMICVINE_CDN_HOSTS = frozenset(
    "static.comicvine.com" if index == 0 else f"static{index}.comicvine.com"
    for index in range(6)
)
_COMICVINE_CANONICAL_SCHEME = "https"
_COMICVINE_CANONICAL_HOST = "comicvine.gamespot.com"
_COMICVINE_CANONICAL_PATH_PREFIX = "/a"

# In-memory DNS resolution cache (hostname -> (is_public, expires_at))
_DNS_CACHE: dict[str, tuple[bool, datetime]] = {}
_DNS_CACHE_TTL = timedelta(hours=1)

# Default cache TTL for optimized images (1 year to match edge cache headers)
_DEFAULT_CACHE_TTL_SECONDS = 31536000


class ImageDeliveryError(Exception):
    """Base error for remote image delivery failures."""


class InvalidImageSourceError(ImageDeliveryError):
    """Raised when a source URL is not an allowlisted, safely routable image."""


class UpstreamImageUnavailableError(ImageDeliveryError):
    """Raised when an allowlisted upstream image cannot be fetched or decoded."""


@dataclass(frozen=True)
class OptimizedImage:
    """Result of fetching and optimizing one remote cover variant."""

    content: bytes
    media_type: str
    width: int
    transcoded: bool


@dataclass(frozen=True)
class OptimizationTimings:
    """Phase timings for image optimization."""

    total_ms: float
    canonicalize_ms: float
    validate_ms: float
    dns_check_ms: float
    cache_lookup_ms: float
    fetch_upstream_ms: float
    transcode_ms: float
    cache_store_ms: float
    cache_hit: bool


def resolve_variant_width(requested_width: int) -> int:
    """Snap a requested render width to a bounded supported bucket.

    Widths snap upward to the smallest supported bucket that satisfies the
    request so browser variants stay finite and CDN-cacheable.

    Args:
        requested_width: Desired rendered width in pixels.

    Returns:
        The nearest supported width bucket, clamped to the largest bucket.
    """
    if requested_width <= SUPPORTED_WIDTHS[0]:
        return SUPPORTED_WIDTHS[0]
    for bucket in SUPPORTED_WIDTHS:
        if requested_width <= bucket:
            return bucket
    return SUPPORTED_WIDTHS[-1]


def canonicalize_source_url(source_url: str) -> str:
    """Resolve a recognized cover CDN alias onto the origin that serves the bytes.

    ComicVine hands out ``http(s)://static*.comicvine.com/uploads/...`` cover URLs
    that its CDN redirects to ``https://comicvine.gamespot.com/a/uploads/...``.
    The optimizer never follows redirects, so an unrewritten alias can never
    deliver a cover. This mapping is a fixed host/path substitution over a fixed
    host set, so it cannot widen which origins are reachable; the result is still
    revalidated by :func:`validate_source_url` before any network call.

    URLs that are not a ComicVine CDN alias are returned unchanged.

    Args:
        source_url: Canonical external image URL from persisted ComicPile data.

    Returns:
        The URL to fetch. Identical to ``source_url`` for non-ComicVine hosts.
    """
    try:
        parts = urlsplit(source_url)
    except ValueError:
        return source_url
    hostname = parts.hostname or ""
    if hostname.lower() not in _COMICVINE_CDN_HOSTS:
        return source_url

    path = parts.path
    if not path.startswith(f"{_COMICVINE_CANONICAL_PATH_PREFIX}/"):
        path = f"{_COMICVINE_CANONICAL_PATH_PREFIX}{path}"
    return urlunsplit(
        (
            _COMICVINE_CANONICAL_SCHEME,
            _COMICVINE_CANONICAL_HOST,
            path,
            parts.query,
            "",
        )
    )


def validate_source_url(source_url: str) -> str:
    """Validate a candidate upstream image URL against the delivery allowlist.

    Args:
        source_url: Canonical external image URL from persisted ComicPile data.

    Returns:
        The validated URL string.

    Raises:
        InvalidImageSourceError: If the URL is malformed, uses a disallowed
            scheme, embeds credentials, or points at a non-allowlisted host.
    """
    if not source_url or len(source_url) > _MAX_SOURCE_URL_LENGTH:
        raise InvalidImageSourceError("Image source URL is missing or too long")

    try:
        parts = urlsplit(source_url)
    except ValueError as exc:
        raise InvalidImageSourceError("Image source URL could not be parsed") from exc

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidImageSourceError("Image source URL must use http or https")
    if parts.username or parts.password:
        raise InvalidImageSourceError("Image source URL must not embed credentials")

    hostname = parts.hostname
    if not hostname:
        raise InvalidImageSourceError("Image source URL has no host")

    allowed_hosts = {
        host.strip().lower()
        for host in get_image_delivery_settings().image_optimizer_allowed_hosts.split(",")
        if host.strip()
    }
    if hostname.lower() not in allowed_hosts:
        raise InvalidImageSourceError("Image host is not on the ComicPile allowlist")

    return source_url


def _resolve_addresses_blocking(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve a hostname to every address family reported by the resolver.

    Args:
        hostname: Upstream hostname to resolve.

    Returns:
        All resolved IP addresses.

    Raises:
        OSError: If DNS resolution fails.
    """
    infos = socket.getaddrinfo(hostname, None)
    return [ipaddress.ip_address(info[4][0]) for info in infos]


async def ensure_publicly_routable(hostname: str) -> None:
    """Reject hostnames that resolve to non-public network ranges.

    Protects against SSRF-style abuse of the optimizer endpoint even if an
    allowlisted host (or an attacker-controllable DNS record for one) resolves
    to loopback, private, link-local, reserved, or multicast space.

    Uses an in-memory cache to avoid repeated DNS resolution for the same host.

    Args:
        hostname: Upstream hostname about to be fetched.

    Raises:
        InvalidImageSourceError: If resolution fails or any address is
            non-public.
    """
    now = datetime.now(UTC)

    # Check cache first
    cached = _DNS_CACHE.get(hostname.lower())
    if cached:
        is_public, expires_at = cached
        if expires_at > now:
            if not is_public:
                raise InvalidImageSourceError("Upstream image host resolves to a non-public address")
            return

    # Not cached or expired - perform DNS resolution
    try:
        addresses = await asyncio.to_thread(_resolve_addresses_blocking, hostname)
    except OSError as exc:
        # Cache negative result for shorter TTL
        _DNS_CACHE[hostname.lower()] = (False, now + timedelta(minutes=5))
        raise InvalidImageSourceError("Upstream image host could not be resolved") from exc

    if not addresses:
        _DNS_CACHE[hostname.lower()] = (False, now + timedelta(minutes=5))
        raise InvalidImageSourceError("Upstream image host did not resolve")

    is_public = True
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            is_public = False
            break

    # Cache the result
    _DNS_CACHE[hostname.lower()] = (is_public, now + _DNS_CACHE_TTL)

    if not is_public:
        raise InvalidImageSourceError("Upstream image host resolves to a non-public address")


def _generate_cache_key(validated_url: str, target_width: int) -> str:
    """Generate a deterministic cache key for an optimized image."""
    key_material = f"{validated_url}|{target_width}".encode("utf-8")
    return hashlib.sha256(key_material).hexdigest()


async def fetch_upstream(
    source_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """Fetch an allowlisted upstream cover image with strict response checks.

    Redirects are intentionally not followed: a validated source must never be
    able to bounce the fetcher toward an unvalidated destination.

    Args:
        source_url: Already-validated absolute image URL.
        transport: Optional httpx transport override (used by tests).

    Returns:
        Tuple of raw payload bytes and the upstream media type.

    Raises:
        UpstreamImageUnavailableError: On network failure, non-200 status,
            non-image content type, or oversized payload.
    """
    settings = get_image_delivery_settings()
    max_bytes = settings.image_optimizer_max_upstream_bytes

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(settings.image_optimizer_upstream_timeout_seconds),
        headers={
            "User-Agent": _UPSTREAM_USER_AGENT,
            "Accept": "image/*",
        },
        transport=transport,
    ) as client:
        try:
            response = await client.get(source_url)
        except httpx.HTTPError as exc:
            raise UpstreamImageUnavailableError("Upstream image request failed") from exc

        if response.status_code != 200:
            raise UpstreamImageUnavailableError(
                f"Upstream image returned HTTP {response.status_code}"
            )

        content_type = response.headers.get("content-type", "").strip()
        if not content_type.lower().startswith("image/"):
            raise UpstreamImageUnavailableError("Upstream response is not an image")

        declared_length = response.headers.get("content-length")
        if declared_length:
            try:
                if int(declared_length) > max_bytes:
                    raise UpstreamImageUnavailableError("Upstream image exceeds size limit")
            except ValueError:
                pass

        chunks: list[bytes] = []
        received = 0
        async for chunk in response.aiter_bytes(64 * 1024):
            received += len(chunk)
            if received > max_bytes:
                raise UpstreamImageUnavailableError("Upstream image exceeds size limit")
            chunks.append(chunk)

    return b"".join(chunks), content_type


def transcode_to_webp(payload: bytes, target_width: int) -> tuple[bytes, str] | None:
    """Downscale and re-encode an image payload as WebP.

    Never upscales; smaller sources are returned at their intrinsic size. When
    Pillow (or the specific payload) is unavailable the caller falls back to
    serving validated original bytes.

    Args:
        payload: Raw upstream image bytes of a verified ``image/*`` type.
        target_width: Maximum output width in pixels.

    Returns:
        Tuple of WebP bytes and the WebP media type, or ``None`` when the
        payload cannot be transcoded in this environment.
    """
    settings = get_image_delivery_settings()
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.width > target_width:
                new_height = max(1, round(image.height * target_width / image.width))
                image = image.resize((target_width, new_height), Image.Resampling.LANCZOS)
            has_alpha = image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            )
            converted = image.convert("RGBA" if has_alpha else "RGB")
            buffer = io.BytesIO()
            converted.save(buffer, format="WEBP", quality=settings.image_optimizer_webp_quality)
            return buffer.getvalue(), "image/webp"
    except ImportError:
        logger.warning("Pillow unavailable; serving remote covers without transformation")
    except Exception as exc:
        logger.warning("Remote cover transcode failed; serving original bytes: %s", exc)
    return None


async def optimize_remote_image(
    source_url: str,
    requested_width: int,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    db: Optional["AsyncSession"] = None,
) -> OptimizedImage:
    """Turn a canonical external image URL into optimized, cacheable bytes.

    Args:
        source_url: Canonical external image URL (never rewritten at rest).
        requested_width: Desired rendered width in pixels.
        transport: Optional httpx transport override (used by tests).
        db: Optional database session for persistent caching.

    Returns:
        An :class:`OptimizedImage` ready to serve with long-lived edge caching.

    Raises:
        InvalidImageSourceError: If validation or SSRF checks fail.
        UpstreamImageUnavailableError: If the upstream fetch fails.
    """
    start_total = time.perf_counter()
    timings = {}

    # Phase 1: Canonicalize
    start = time.perf_counter()
    validated_url = validate_source_url(canonicalize_source_url(source_url))
    timings["canonicalize_ms"] = (time.perf_counter() - start) * 1000

    # Phase 2: DNS check (with caching)
    hostname = urlsplit(validated_url).hostname or ""
    start = time.perf_counter()
    await ensure_publicly_routable(hostname)
    timings["dns_check_ms"] = (time.perf_counter() - start) * 1000

    # Phase 3: Determine target width
    target_width = resolve_variant_width(requested_width)

    # Phase 4: Check persistent cache
    cache_key = _generate_cache_key(validated_url, target_width)
    cache_hit = False
    cache_lookup_start = time.perf_counter()

    cached_result: Optional[OptimizedImage] = None
    if db is not None:
        repo = ImageOptimizationCacheRepository(db)
        cached_entry = await repo.get(cache_key)
        if cached_entry is not None:
            cached_result = OptimizedImage(
                content=cached_entry.content,
                media_type=cached_entry.media_type,
                width=cached_entry.width,
                transcoded=cached_entry.transcoded,
            )
            cache_hit = True

    timings["cache_lookup_ms"] = (time.perf_counter() - cache_lookup_start) * 1000

    if cache_hit:
        timings["fetch_upstream_ms"] = 0.0
        timings["transcode_ms"] = 0.0
        timings["cache_store_ms"] = 0.0
        timings["total_ms"] = (time.perf_counter() - start_total) * 1000

        logger.info(
            "Image optimization cache hit",
            extra={
                "cache_key": cache_key[:16],
                "source_url": validated_url,
                "width": target_width,
                "timings_ms": timings,
            },
        )
        return cached_result

    # Phase 5: Fetch upstream
    start = time.perf_counter()
    payload, content_type = await fetch_upstream(validated_url, transport=transport)
    timings["fetch_upstream_ms"] = (time.perf_counter() - start) * 1000

    # Phase 6: Transcode
    start = time.perf_counter()
    transcoded = transcode_to_webp(payload, target_width)
    timings["transcode_ms"] = (time.perf_counter() - start) * 1000

    if transcoded is not None:
        result = OptimizedImage(
            content=transcoded[0],
            media_type=transcoded[1],
            width=target_width,
            transcoded=True,
        )
    else:
        result = OptimizedImage(
            content=payload,
            media_type=content_type.split(";")[0].strip().lower() or "application/octet-stream",
            width=target_width,
            transcoded=False,
        )

    # Phase 7: Store in persistent cache
    if db is not None:
        start = time.perf_counter()
        repo = ImageOptimizationCacheRepository(db)
        try:
            await repo.set(
                cache_key=cache_key,
                source_url=validated_url,
                width=target_width,
                content=result.content,
                media_type=result.media_type,
                transcoded=result.transcoded,
                ttl_seconds=_DEFAULT_CACHE_TTL_SECONDS,
            )
            await db.commit()
        except Exception as exc:
            logger.warning("Failed to store image in cache: %s", exc)
            await db.rollback()
        timings["cache_store_ms"] = (time.perf_counter() - start) * 1000
    else:
        timings["cache_store_ms"] = 0.0

    timings["total_ms"] = (time.perf_counter() - start_total) * 1000

    logger.info(
        "Image optimization completed",
        extra={
            "cache_key": cache_key[:16],
            "source_url": validated_url,
            "width": target_width,
            "cache_hit": cache_hit,
            "transcoded": result.transcoded,
            "content_length": len(result.content),
            "timings_ms": timings,
        },
    )

    return result