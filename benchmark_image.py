"""Benchmark script for image optimization performance."""

import asyncio
import time
import io
from PIL import Image
import httpx
from app.services.image_delivery import (
    optimize_remote_image,
    canonicalize_source_url,
    validate_source_url,
    ensure_publicly_routable,
    fetch_upstream,
    transcode_to_webp,
    resolve_variant_width,
)
from app.config import get_image_delivery_settings
from urllib.parse import urlsplit

# Create a test image
def create_test_image(width=800, height=1200):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color=(140, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()

# Mock transport for testing
class MockTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload, media_type="image/jpeg"):
        self.payload = payload
        self.media_type = media_type
        self.call_count = 0
    
    async def handle_async_request(self, request):
        self.call_count += 1
        return httpx.Response(
            200,
            headers={"content-type": self.media_type},
            content=self.payload,
        )

async def benchmark():
    # Test URL (ComicVine canonical)
    test_url = "https://comicvine.gamespot.com/a/uploads/scale_large/0/1/100-1.jpg"
    test_width = 240
    
    # Create test image payload
    test_payload = create_test_image(800, 1200)
    transport = MockTransport(test_payload)
    
    print("=== Benchmarking Image Optimization ===\n")
    
    # 1. Canonicalize
    start = time.perf_counter()
    canonical = canonicalize_source_url(test_url)
    t1 = time.perf_counter() - start
    print(f"1. canonicalize_source_url: {t1*1000:.2f}ms")
    print(f"   Result: {canonical}")
    
    # 2. Validate
    start = time.perf_counter()
    validated = validate_source_url(canonical)
    t2 = time.perf_counter() - start
    print(f"2. validate_source_url: {t2*1000:.2f}ms")
    
    # 3. DNS Resolution (SSRF check) - this will fail without real DNS, so we'll mock it
    hostname = urlsplit(validated).hostname or ""
    print(f"   Hostname: {hostname}")
    
    # 4. Fetch upstream
    start = time.perf_counter()
    payload, content_type = await fetch_upstream(validated, transport=transport)
    t4 = time.perf_counter() - start
    print(f"4. fetch_upstream: {t4*1000:.2f}ms")
    print(f"   Payload size: {len(payload)} bytes")
    print(f"   Content-Type: {content_type}")
    
    # 5. Resolve variant width
    start = time.perf_counter()
    target_width = resolve_variant_width(test_width)
    t5 = time.perf_counter() - start
    print(f"5. resolve_variant_width: {t5*1000:.2f}ms")
    print(f"   Target width: {target_width}")
    
    # 6. Transcode to WebP
    start = time.perf_counter()
    transcoded = transcode_to_webp(payload, target_width)
    t6 = time.perf_counter() - start
    print(f"6. transcode_to_webp: {t6*1000:.2f}ms")
    if transcoded:
        print(f"   Transcoded size: {len(transcoded[0])} bytes")
        print(f"   Media type: {transcoded[1]}")
    
    # 7. Full optimize_remote_image (with mocked DNS)
    import app.services.image_delivery as img_delivery
    
    async def mock_ensure_public(hostname):
        return None
    
    original_ensure = img_delivery.ensure_publicly_routable
    img_delivery.ensure_publicly_routable = mock_ensure_public
    
    try:
        start = time.perf_counter()
        result = await optimize_remote_image(test_url, test_width, transport=transport)
        t7 = time.perf_counter() - start
        print(f"\n7. Full optimize_remote_image (mocked): {t7*1000:.2f}ms")
        print(f"   Result: width={result.width}, media_type={result.media_type}, transcoded={result.transcoded}, size={len(result.content)}")
    finally:
        img_delivery.ensure_publicly_routable = original_ensure
    
    print(f"\n=== Summary ===")
    print(f"Total (mocked): {t1*1000 + t2*1000 + t4*1000 + t5*1000 + t6*1000:.2f}ms")

if __name__ == "__main__":
    asyncio.run(benchmark())
