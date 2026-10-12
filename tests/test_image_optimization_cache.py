"""Tests for the persistent image-optimization cache (issue #3249).

Production reads of ``GET /api/v1/images/optimize`` were measured at ~1.8 s
because every warm request re-fetched and re-transcoded the same upstream cover.
The optimizer now keeps optimized variants in PostgreSQL so a repeat request is
answered from stored bytes instead of upstream work. These tests pin that
contract directly, plus the expiry and eviction rules that keep stored bytes
bounded and never serve a stale variant.

The service-level cases clear the process-local caches between the cold and warm
calls, so a passing warm path can only have been answered by the persistent
store.
"""

from __future__ import annotations

import io
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.image_optimization_cache import ImageOptimizationCache
from app.repositories.image_optimization_cache_repository import (
    ImageOptimizationCacheRepository,
)
from app.services import image_delivery
from app.services.image_delivery import optimize_remote_image

ALLOWED_SOURCE = "https://comicvine.gamespot.com/a/uploads/scale_large/0/1/100-1.jpg"
OTHER_SOURCE = "https://comicvine.gamespot.com/a/uploads/scale_large/0/1/200-2.jpg"

# Issue #3249 budgets warm common-path requests below 500 ms. The warm path here
# is a primary-key lookup plus in-process reads, so the ceiling is generous
# enough to stay stable on a loaded CI runner while still failing loudly if a
# future change reintroduces synchronous upstream work.
WARM_REQUEST_BUDGET_SECONDS = 0.5


def _png_bytes(width: int = 800, height: int = 1200) -> bytes:
    """Build a deterministic PNG payload for upstream simulation."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(140, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _allow_all_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace DNS validation with a no-op so only caching is under test."""

    async def _public(hostname: str) -> None:
        return None

    monkeypatch.setattr(image_delivery, "ensure_publicly_routable", _public)


def _recording_fetch(
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    media_type: str = "image/jpeg",
) -> list[str]:
    """Replace upstream fetching with canned bytes and return the call log."""
    calls: list[str] = []

    async def _fetch(
        url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> tuple[bytes, str]:
        calls.append(url)
        return payload, media_type

    monkeypatch.setattr(image_delivery, "fetch_upstream", _fetch)
    return calls


def _cache_entry(
    cache_key: str,
    *,
    content: bytes,
    expires_at: datetime,
) -> ImageOptimizationCache:
    """Build a stored cache row with explicit content and expiry."""
    return ImageOptimizationCache(
        cache_key=cache_key,
        source_url=ALLOWED_SOURCE,
        width=240,
        content=content,
        media_type="image/webp",
        transcoded=True,
        content_length=len(content),
        expires_at=expires_at,
    )


def test_cache_key_is_deterministic_and_variant_scoped() -> None:
    """One source and width always map to one key; variants never collide."""
    first = image_delivery._generate_cache_key(ALLOWED_SOURCE, 240)

    assert first == image_delivery._generate_cache_key(ALLOWED_SOURCE, 240)
    assert first != image_delivery._generate_cache_key(ALLOWED_SOURCE, 480)
    assert first != image_delivery._generate_cache_key(OTHER_SOURCE, 240)
    assert len(first) == 64


@pytest.mark.asyncio
async def test_stored_variant_round_trips_unchanged(db: AsyncSession) -> None:
    """A stored variant is returned with identical bytes and metadata."""
    repository = ImageOptimizationCacheRepository(db)
    payload = _png_bytes(width=240, height=360)

    await repository.set(
        cache_key="round-trip",
        source_url=ALLOWED_SOURCE,
        width=240,
        content=payload,
        media_type="image/webp",
        transcoded=True,
    )
    await db.flush()

    stored = await repository.get("round-trip")

    assert stored is not None
    assert stored.content == payload
    assert stored.media_type == "image/webp"
    assert stored.width == 240
    assert stored.transcoded is True
    assert stored.content_length == len(payload)


@pytest.mark.asyncio
async def test_get_skips_expired_entries(db: AsyncSession) -> None:
    """An entry past its expiry is treated as absent."""
    repository = ImageOptimizationCacheRepository(db)
    db.add(
        _cache_entry(
            "stale",
            content=b"stale-bytes",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db.flush()

    assert await repository.get("stale") is None


@pytest.mark.asyncio
async def test_delete_expired_removes_only_expired_entries(db: AsyncSession) -> None:
    """Eviction reclaims stale rows and leaves live variants servable."""
    repository = ImageOptimizationCacheRepository(db)
    now = datetime.now(UTC)
    for cache_key, expires_at in (
        ("stale-a", now - timedelta(minutes=1)),
        ("stale-b", now - timedelta(days=1)),
        ("live-a", now + timedelta(days=1)),
    ):
        db.add(_cache_entry(cache_key, content=b"bytes", expires_at=expires_at))
    await db.flush()

    assert await repository.delete_expired() == 2
    assert await repository.get("live-a") is not None


@pytest.mark.asyncio
async def test_warm_request_is_served_without_upstream_work(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """A repeat request is answered from stored bytes, not upstream (#3249)."""
    _allow_all_resolver(monkeypatch)
    upstream_calls = _recording_fetch(monkeypatch, _png_bytes())
    original_transcode = image_delivery.transcode_to_webp
    transcode_calls: list[bytes] = []

    def _counting_transcode(payload: bytes, target_width: int) -> tuple[bytes, str] | None:
        transcode_calls.append(payload)
        return original_transcode(payload, target_width)

    monkeypatch.setattr(image_delivery, "transcode_to_webp", _counting_transcode)

    cold = await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)
    assert upstream_calls == [ALLOWED_SOURCE]
    assert len(transcode_calls) == 1

    # Drop the process-local caches so only the persistent store can answer.
    image_delivery.clear_caches()

    started = time.perf_counter()
    warm = await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)
    elapsed = time.perf_counter() - started

    assert upstream_calls == [ALLOWED_SOURCE]
    assert len(transcode_calls) == 1
    assert warm.content == cold.content
    assert warm.media_type == cold.media_type
    assert warm.width == cold.width
    assert warm.transcoded == cold.transcoded
    assert elapsed < WARM_REQUEST_BUDGET_SECONDS


@pytest.mark.asyncio
async def test_warm_request_does_not_share_bytes_across_variants(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """A different width is a different variant and still reaches upstream."""
    _allow_all_resolver(monkeypatch)
    upstream_calls = _recording_fetch(monkeypatch, _png_bytes())

    await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)
    image_delivery.clear_caches()
    wide = await optimize_remote_image(ALLOWED_SOURCE, 720, db=db)

    assert upstream_calls == [ALLOWED_SOURCE, ALLOWED_SOURCE]
    assert wide.width == 720


@pytest.mark.asyncio
async def test_expired_stored_variant_is_refetched_then_cached_again(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """An expired variant is refetched once, then served from the refreshed row.

    Reads filter expired rows but never delete them, so a store that cannot
    replace an existing row would refetch that cover forever. That is exactly
    the repeated upstream work #3249 removed.
    """
    _allow_all_resolver(monkeypatch)
    upstream_calls = _recording_fetch(monkeypatch, _png_bytes(width=400, height=600))
    cache_key = image_delivery._generate_cache_key(ALLOWED_SOURCE, 240)
    await ImageOptimizationCacheRepository(db).set(
        cache_key=cache_key,
        source_url=ALLOWED_SOURCE,
        width=240,
        content=b"stale-bytes",
        media_type="image/webp",
        transcoded=True,
        ttl_seconds=-60,
    )
    image_delivery.clear_caches()

    first = await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)

    assert upstream_calls == [ALLOWED_SOURCE]
    assert first.content != b"stale-bytes"
    assert first.width == 240

    image_delivery.clear_caches()
    second = await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)

    assert upstream_calls == [ALLOWED_SOURCE]
    assert second.content == first.content


@pytest.mark.asyncio
async def test_cache_store_failure_still_serves_the_image(
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """A cache write error never turns a good cover into a failed response."""
    _allow_all_resolver(monkeypatch)
    _recording_fetch(monkeypatch, _png_bytes())

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("cache store unavailable")

    monkeypatch.setattr(ImageOptimizationCacheRepository, "set", _boom)

    result = await optimize_remote_image(ALLOWED_SOURCE, 240, db=db)

    assert result.width == 240
    assert result.content