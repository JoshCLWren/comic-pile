"""Edge-cacheable remote comic cover image delivery.

ComicPile stores canonical third-party cover-art URLs (typically ComicVine
uploads) in its database. Rendering those URLs directly couples the browser to
the upstream host for latency, availability, cache behavior, and format. This
service is the single sanctioned transformation point between canonical source
URLs and the bytes the browser receives:

- only explicitly allowlisted upstream hosts are fetched;
- resolved addresses must be publicly routable (SSRF protection);
- payloads are size-capped and content-type-checked;
- images are downscaled to bounded width buckets and re-encoded as WebP, or as
  AVIF when the runtime encoder is available, falling back to validated
  passthrough bytes;
- responses are marked immutable and shared-cacheable so Vercel's CDN serves
  repeat requests from the edge instead of refetching the upstream host.
"""

import asyncio
import io
import ipaddress
import logging
import socket
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

import httpx

from app.config import get_image_delivery_settings

logger = logging.getLogger(__name__)

SUPPORTED_WIDTHS = (96, 240, 480, 720)

_MAX_SOURCE_URL_LENGTH = 2048

_ALLOWED_SCHEMES = ("http", "https")

_UPSTREAM_USER_AGENT = "ComicPileImageOptimizer/1.0"


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

    Args:
        hostname: Upstream hostname about to be fetched.

    Raises:
        InvalidImageSourceError: If resolution fails or any address is
            non-public.
    """
    try:
        addresses = await asyncio.to_thread(_resolve_addresses_blocking, hostname)
    except OSError as exc:
        raise InvalidImageSourceError("Upstream image host could not be resolved") from exc

    if not addresses:
        raise InvalidImageSourceError("Upstream image host did not resolve")

    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise InvalidImageSourceError("Upstream image host resolves to a non-public address")


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


@lru_cache
def avif_encoding_available() -> bool:
    """Report whether this runtime can encode AVIF payloads.

    Pillow only registers the AVIF encoder when it was built against libavif, so
    the capability is probed once per process instead of on every request. That
    keeps the AVIF fallback deterministic and avoids logging a warning for every
    cover a runtime without libavif is asked to deliver.

    Returns:
        True when Pillow can encode AVIF, False when it cannot.
    """
    try:
        from PIL import Image

        return "AVIF" in set(Image.registered_extensions().values())
    except ImportError:
        return False


def transcode_to_avif(payload: bytes, target_width: int) -> tuple[bytes, str] | None:
    """Downscale and re-encode an image payload as AVIF.

    Never upscales; smaller sources are returned at their intrinsic size. When
    the payload cannot be transcoded (libavif unavailable, Pillow unavailable,
    or corrupted payload) the caller falls back to the WebP pipeline so the
    delivered variant is still downscaled and modern.

    Args:
        payload: Raw upstream image bytes of a verified ``image/*`` type.
        target_width: Maximum output width in pixels.

    Returns:
        Tuple of AVIF bytes and the AVIF media type, or ``None`` when this
        environment cannot produce AVIF for the payload.
    """
    if not avif_encoding_available():
        return None
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
            converted.save(buffer, format="AVIF", quality=settings.image_optimizer_avif_quality)
            return buffer.getvalue(), "image/avif"
    except ImportError:
        logger.warning("Pillow unavailable; serving remote covers without transformation")
    except Exception as exc:
        logger.warning("Remote cover AVIF transcode failed; falling back to WebP: %s", exc)
    return None


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


def transcode_to_modern_format(
    payload: bytes, target_width: int, format: Literal["webp", "avif"] = "webp",
) -> tuple[bytes, str] | None:
    """Downscale and re-encode an image payload as a modern lossy format.

    Never upscales; smaller sources are returned at their intrinsic size. When
    the requested format cannot be produced (missing encoder or corrupt payload)
    the caller decides whether to try another modern format or fall back to
    validated passthrough bytes.

    Args:
        payload: Raw upstream image bytes of a verified ``image/*`` type.
        target_width: Maximum output width in pixels.
        format: ``webp`` or ``avif``.

    Returns:
        Tuple of encoded bytes and the encoded media type, or ``None`` when the
        requested format cannot be produced in this environment.
    """
    if format == "avif":
        return transcode_to_avif(payload, target_width)
    return transcode_to_webp(payload, target_width)


async def optimize_remote_image(
    source_url: str,
    requested_width: int,
    *,
    format: Literal["webp", "avif"] = "webp",
    transport: httpx.AsyncBaseTransport | None = None,
) -> OptimizedImage:
    """Turn a canonical external image URL into optimized, cacheable bytes.

    Args:
        source_url: Canonical external image URL (never rewritten at rest).
        requested_width: Desired rendered width in pixels.
        format: ``webp`` is deterministic. ``avif`` prefers AVIF and falls back
            to WebP so a browser that selected an AVIF candidate still receives
            a downscaled modern variant instead of the full-size original.
        transport: Optional httpx transport override (used by tests).

    Returns:
        An :class:`OptimizedImage` ready to serve with long-lived edge caching.

    Raises:
        InvalidImageSourceError: If validation or SSRF checks fail.
        UpstreamImageUnavailableError: If the upstream fetch fails.
    """
    validated_url = validate_source_url(source_url)
    hostname = urlsplit(validated_url).hostname or ""
    await ensure_publicly_routable(hostname)

    target_width = resolve_variant_width(requested_width)
    payload, content_type = await fetch_upstream(validated_url, transport=transport)

    candidates: tuple[Literal["avif", "webp"], ...]
    if format == "avif":
        candidates = ("avif", "webp")
    else:
        candidates = ("webp",)

    for candidate in candidates:
        transcoded = await asyncio.to_thread(
            transcode_to_modern_format, payload, target_width, candidate
        )
        if transcoded is None:
            continue
        content, media_type = transcoded
        return OptimizedImage(
            content=content,
            media_type=media_type,
            width=target_width,
            transcoded=True,
        )

    return OptimizedImage(
        content=payload,
        media_type=content_type.split(";")[0].strip().lower() or "application/octet-stream",
        width=target_width,
        transcoded=False,
    )
