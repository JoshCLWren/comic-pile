"""Tests for the edge-cacheable remote cover image optimizer (issue #1914).

Covers URL allowlisting, SSRF guards, width bucketing, WebP transformation,
cache headers, and failure behavior. All network access is mocked via httpx
transports and patched resolvers, so this module needs no database or live
upstream host.
"""

import asyncio
import io
import ipaddress
from collections.abc import AsyncIterator

import httpx
import pytest
from PIL import Image

from app.main import create_app
from app.services import image_delivery
from app.services.image_delivery import (
    InvalidImageSourceError,
    UpstreamImageUnavailableError,
    fetch_upstream,
    optimize_remote_image,
    resolve_variant_width,
    validate_source_url,
)

ALLOWED_HOST = "comicvine.gamespot.com"
ALLOWED_SOURCE = f"https://{ALLOWED_HOST}/a/uploads/scale_large/0/1/100-1.jpg"


def _png_bytes(width: int = 800, height: int = 1200) -> bytes:
    """Build a deterministic PNG payload for upstream simulation."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(140, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _image_dimensions(payload: bytes) -> tuple[int, int]:
    """Decode an image payload to its pixel dimensions."""
    with Image.open(io.BytesIO(payload)) as decoded:
        return decoded.size


def _transport_with(
    payload: bytes,
    media_type: str = "image/jpeg",
    status_code: int = 200,
) -> httpx.MockTransport:
    """Build an httpx mock transport serving one canned image response."""
    return httpx.MockTransport(
        lambda request: httpx.Response(
            status_code,
            headers={"content-type": media_type},
            content=payload,
        )
    )


def _allow_all_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace DNS validation with a no-op for API-level success tests."""

    async def _public(hostname: str) -> None:
        return None

    monkeypatch.setattr(image_delivery, "ensure_publicly_routable", _public)


def _canned_fetch(monkeypatch: pytest.MonkeyPatch, payload: bytes, media_type: str) -> None:
    """Replace upstream fetching with canned bytes."""

    async def _fetch(
        url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> tuple[bytes, str]:
        return payload, media_type

    monkeypatch.setattr(image_delivery, "fetch_upstream", _fetch)


class TestVariantWidthBuckets:
    """Requested widths snap onto the finite supported variant set."""

    @pytest.mark.parametrize(
        ("requested", "expected"),
        [
            (16, 96),
            (95, 96),
            (96, 96),
            (97, 240),
            (240, 240),
            (300, 480),
            (480, 480),
            (600, 720),
            (720, 720),
            (2048, 720),
        ],
    )
    def test_widths_snap_to_supported_buckets(self, requested: int, expected: int) -> None:
        assert resolve_variant_width(requested) == expected


class TestSourceUrlValidation:
    """Only allowlisted, credential-free http(s) sources are accepted."""

    def test_accepts_allowlisted_https_source(self) -> None:
        assert validate_source_url(ALLOWED_SOURCE) == ALLOWED_SOURCE

    def test_accepts_allowlisted_legacy_host(self) -> None:
        url = "https://www.comicvine.com/api/image/scale_large/1-2.jpg"
        assert validate_source_url(url) == url

    def test_rejects_disallowed_host(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url("https://evil.example.com/a/uploads/x.jpg")

    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url(f"ftp://{ALLOWED_HOST}/a/uploads/x.jpg")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url("file:///etc/passwd")

    def test_rejects_missing_host(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url("not-a-url")

    def test_rejects_embedded_credentials(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url(f"https://user:pass@{ALLOWED_HOST}/a/uploads/x.jpg")

    def test_rejects_empty_and_oversized_urls(self) -> None:
        with pytest.raises(InvalidImageSourceError):
            validate_source_url("")
        with pytest.raises(InvalidImageSourceError):
            validate_source_url(f"https://{ALLOWED_HOST}/{'a' * 2100}")


class TestSsrfGuard:
    """Allowlisted hosts must still resolve to public addresses only."""

    @pytest.mark.parametrize(
        ("address", "flag"),
        [
            ("127.0.0.1", "is_loopback"),
            ("10.1.2.3", "is_private"),
            ("192.168.0.5", "is_private"),
            ("172.16.0.9", "is_private"),
            ("169.254.169.254", "is_link_local"),
            ("::1", "is_loopback"),
        ],
    )
    def test_private_addresses_are_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        address: str,
        flag: str,
    ) -> None:
        resolved = [ipaddress.ip_address(address)]
        assert getattr(resolved[0], flag), f"fixture address {address} must be {flag}"
        monkeypatch.setattr(
            image_delivery,
            "_resolve_addresses_blocking",
            lambda hostname: resolved,
        )

        async def _check() -> None:
            await image_delivery.ensure_publicly_routable(ALLOWED_HOST)

        with pytest.raises(InvalidImageSourceError):
            asyncio.run(_check())

    def test_public_addresses_are_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            image_delivery,
            "_resolve_addresses_blocking",
            lambda hostname: [ipaddress.ip_address("93.184.216.34")],
        )

        async def _check() -> None:
            await image_delivery.ensure_publicly_routable(ALLOWED_HOST)

        asyncio.run(_check())

    def test_unresolvable_host_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
            raise OSError("resolution failed")

        monkeypatch.setattr(image_delivery, "_resolve_addresses_blocking", _raise)

        async def _check() -> None:
            await image_delivery.ensure_publicly_routable(ALLOWED_HOST)

        with pytest.raises(InvalidImageSourceError):
            asyncio.run(_check())


class TestUpstreamFetch:
    """Upstream fetching enforces status, type, redirect, and size limits."""

    async def test_returns_payload_and_media_type(self) -> None:
        payload, media_type = await fetch_upstream(
            f"https://{ALLOWED_HOST}/cover.jpg",
            transport=_transport_with(_png_bytes()),
        )
        assert media_type == "image/jpeg"
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")

    async def test_non_200_is_unavailable(self) -> None:
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        with pytest.raises(UpstreamImageUnavailableError):
            await fetch_upstream(f"https://{ALLOWED_HOST}/cover.jpg", transport=transport)

    async def test_redirects_are_not_followed(self) -> None:
        def _redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://evil.example.com/x"})

        transport = httpx.MockTransport(_redirect)
        with pytest.raises(UpstreamImageUnavailableError):
            await fetch_upstream(f"https://{ALLOWED_HOST}/cover.jpg", transport=transport)

    async def test_non_image_content_type_is_rejected(self) -> None:
        transport = _transport_with(b"<html>not an image</html>", media_type="text/html")
        with pytest.raises(UpstreamImageUnavailableError):
            await fetch_upstream(f"https://{ALLOWED_HOST}/cover.jpg", transport=transport)

    @pytest.mark.parametrize("declare_length", [True, False])
    async def test_oversized_body_is_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        declare_length: bool,
    ) -> None:
        monkeypatch.setenv("IMAGE_OPTIMIZER_MAX_UPSTREAM_BYTES", "100")
        image_delivery.get_image_delivery_settings.cache_clear()
        try:
            big_payload = b"x" * 5000
            headers = {"content-type": "image/jpeg"}
            if declare_length:
                headers["content-length"] = str(len(big_payload))
            transport = httpx.MockTransport(
                lambda request: httpx.Response(200, headers=headers, content=big_payload)
            )
            with pytest.raises(UpstreamImageUnavailableError):
                await fetch_upstream(f"https://{ALLOWED_HOST}/cover.jpg", transport=transport)
        finally:
            image_delivery.get_image_delivery_settings.cache_clear()


class TestOptimizeRemoteImage:
    """End-to-end service behavior with mocked network and resolver."""

    async def test_downscales_to_requested_bucket_as_webp(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _allow_all_resolver(monkeypatch)
        result = await optimize_remote_image(
            ALLOWED_SOURCE,
            240,
            transport=_transport_with(_png_bytes(width=800, height=1200)),
        )
        assert result.media_type == "image/webp"
        assert result.width == 240
        assert result.transcoded is True
        assert _image_dimensions(result.content)[0] <= 240

    async def test_never_upscales_smaller_sources(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _allow_all_resolver(monkeypatch)
        result = await optimize_remote_image(
            f"https://{ALLOWED_HOST}/small.jpg",
            480,
            transport=_transport_with(_png_bytes(width=64, height=96)),
        )
        assert _image_dimensions(result.content) == (64, 96)

    async def test_transcode_failure_falls_back_to_original_bytes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _allow_all_resolver(monkeypatch)
        original = _png_bytes()
        monkeypatch.setattr(image_delivery, "transcode_to_webp", lambda payload, target_width: None)

        result = await optimize_remote_image(
            f"https://{ALLOWED_HOST}/odd.jpg",
            96,
            transport=_transport_with(original, media_type="image/jpeg; charset=binary"),
        )
        assert result.transcoded is False
        assert result.media_type == "image/jpeg"
        assert result.content == original

    async def test_invalid_source_never_reaches_the_network(self) -> None:
        def _fail(request: httpx.Request) -> httpx.Response:
            raise AssertionError("network must not be touched for invalid sources")

        with pytest.raises(InvalidImageSourceError):
            await optimize_remote_image(
                "https://evil.example.com/x.jpg",
                240,
                transport=httpx.MockTransport(_fail),
            )


class TestOptimizeEndpoint:
    """HTTP contract of GET /api/v1/images/optimize."""

    ENDPOINT = "/api/v1/images/optimize"

    @pytest.fixture
    def endpoint_url(self) -> str:
        """Expose the canonical endpoint path to individual tests."""
        return self.ENDPOINT

    @pytest.fixture
    async def client(self) -> AsyncIterator[httpx.AsyncClient]:
        """ASGI client bound to one application instance per test."""
        application = create_app(serve_frontend=False)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client

    async def test_success_serves_webp_with_edge_cache_headers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        _allow_all_resolver(monkeypatch)
        _canned_fetch(monkeypatch, _png_bytes(width=900, height=1350), "image/jpeg")

        response = await client.get(endpoint_url, params={"url": ALLOWED_SOURCE, "width": 240})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/webp")
        cache_control = response.headers["cache-control"]
        assert "max-age=31536000" in cache_control
        assert "s-maxage=31536000" in cache_control
        assert "stale-while-revalidate" in cache_control
        assert "immutable" in cache_control
        assert response.headers["x-comicpile-image-width"] == "240"
        assert _image_dimensions(response.content)[0] <= 240

    async def test_disallowed_host_is_a_bad_request_without_caching(
        self,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        response = await client.get(
            endpoint_url,
            params={"url": "https://evil.example.com/x.jpg", "width": 240},
        )

        assert response.status_code == 400
        assert response.headers["cache-control"] == "no-store"

    async def test_private_resolution_is_rejected_at_api_layer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        async def _private(hostname: str) -> None:
            raise InvalidImageSourceError("Upstream image host resolves to a non-public address")

        monkeypatch.setattr(image_delivery, "ensure_publicly_routable", _private)

        response = await client.get(endpoint_url, params={"url": ALLOWED_SOURCE, "width": 240})

        assert response.status_code == 400
        assert response.headers["cache-control"] == "no-store"

    async def test_upstream_failure_is_uncached_not_found(
        self,
        monkeypatch: pytest.MonkeyPatch,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        _allow_all_resolver(monkeypatch)

        async def _boom(
            url: str,
            *,
            transport: httpx.AsyncBaseTransport | None = None,
        ) -> tuple[bytes, str]:
            raise UpstreamImageUnavailableError("Upstream image returned HTTP 503")

        monkeypatch.setattr(image_delivery, "fetch_upstream", _boom)

        response = await client.get(endpoint_url, params={"url": ALLOWED_SOURCE, "width": 240})

        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"

    async def test_width_snaps_at_the_http_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        _allow_all_resolver(monkeypatch)
        _canned_fetch(monkeypatch, _png_bytes(width=1600, height=2400), "image/jpeg")

        response = await client.get(
            endpoint_url,
            params={"url": ALLOWED_SOURCE, "width": 10000},
        )

        assert response.status_code == 200
        assert response.headers["x-comicpile-image-width"] == "720"

    async def test_missing_width_parameter_fails_validation(
        self,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        response = await client.get(endpoint_url, params={"url": ALLOWED_SOURCE})

        assert response.status_code == 422

    async def test_invalid_width_parameter_fails_validation(
        self,
        client: httpx.AsyncClient,
        endpoint_url: str,
    ) -> None:
        response = await client.get(endpoint_url, params={"url": ALLOWED_SOURCE, "width": 8})

        assert response.status_code == 422
