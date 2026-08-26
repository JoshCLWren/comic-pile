"""Edge-cacheable comic cover image optimization routes.

Covers are public artwork, so this endpoint is intentionally unauthenticated
(browser ``<img>`` requests cannot attach Authorization headers). Abuse is
bounded instead by the strict upstream host allowlist, DNS SSRF guard, payload
size cap, and finite width buckets enforced by the delivery service.
"""

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from app.services.image_delivery import (
    InvalidImageSourceError,
    UpstreamImageUnavailableError,
    optimize_remote_image,
)

router = APIRouter(prefix="/api/v1/images", tags=["images"])

# Canonical cover URLs are effectively immutable content-addressed sources, so
# both browsers (max-age) and the Vercel shared edge cache (s-maxage) may pin
# them for a year; stale-while-revalidate keeps repeat loads instant while a
# fresh copy revalidates in the background.
_SUCCESS_CACHE_CONTROL = (
    "public, max-age=31536000, s-maxage=31536000, stale-while-revalidate=604800, immutable"
)
_ERROR_CACHE_CONTROL = "no-store"


@router.get("/optimize")
async def api_optimize_remote_image(
    url: Annotated[
        str,
        Query(min_length=1, max_length=2048, description="Canonical external image URL"),
    ],
    width: Annotated[
        int,
        Query(ge=16, le=10000, description="Desired rendered width in pixels"),
    ],
) -> Response:
    """Fetch, optimize, and serve an allowlisted remote cover image.

    Args:
        url: Canonical external image URL from persisted ComicPile data.
        width: Desired rendered width; snapped to a supported variant bucket.

    Returns:
        A binary image response with long-lived shared-cache headers, or an
        error response that must never be cached when the source is unsafe or
        unavailable.
    """
    try:
        result = await optimize_remote_image(url, width)
    except InvalidImageSourceError as exc:
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)},
            headers={"Cache-Control": _ERROR_CACHE_CONTROL},
        )
    except UpstreamImageUnavailableError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
            headers={"Cache-Control": _ERROR_CACHE_CONTROL},
        )

    return Response(
        content=result.content,
        media_type=result.media_type,
        headers={
            "Cache-Control": _SUCCESS_CACHE_CONTROL,
            "X-ComicPile-Image-Width": str(result.width),
        },
    )
