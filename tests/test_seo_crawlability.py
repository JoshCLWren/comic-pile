"""Tests for the public-route indexability policy (issue #3065).

Only the landing page is a crawl target: it must stay servable as meaningful
HTML without JavaScript, expose one stable canonical URL, and remain allowed by
``robots.txt``. Every other SPA path (auth/utility pages, redirects, and all
authenticated routes) must carry ``X-Robots-Tag: noindex, nofollow`` and be
disallowed in ``robots.txt`` so private routes never become crawl targets.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.main import (
    PRODUCTION_ORIGIN,
    _render_sitemap_xml,
    _robots_tag_for_spa_path,
    _SPA_INDEXABLE_PATHS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_INDEX = REPO_ROOT / "frontend" / "index.html"
ROBOTS_SOURCE = REPO_ROOT / "frontend" / "public" / "robots.txt"
SITEMAP_NAMESPACE = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

UTILITY_PATHS = ["/login", "/register", "/forgot-password", "/reset-password", "/demo"]
PRIVATE_PATHS = [
    "/queue",
    "/history",
    "/thread/1",
    "/creators",
    "/creators/some-creator",
    "/sessions/1",
    "/crossovers",
    "/crossovers/group-1",
    "/continuity-plans",
    "/continuity-plans/new",
    "/continuity-plans/2",
    "/whats-new",
    "/glossary",
    "/identity-inbox",
]
NON_INDEXABLE_PATHS = UTILITY_PATHS + PRIVATE_PATHS + ["/rate", "/analytics", "/help"]


def _sitemap_locations(sitemap_text: str) -> list[str]:
    """Parse the ``<loc>`` values out of sitemap XML.

    Args:
        sitemap_text: Sitemap document text.

    Returns:
        Every absolute canonical URL listed in the document.
    """
    root = ET.fromstring(sitemap_text)
    locations: list[str] = []
    for element in root.findall("s:url/s:loc", SITEMAP_NAMESPACE):
        text = element.text
        assert text is not None
        locations.append(text)
    return locations


def test_robots_tag_helper_only_indexes_landing_page() -> None:
    """Only `/` is an intentional crawl target; everything else gets noindex."""
    assert _robots_tag_for_spa_path("/") is None
    assert _robots_tag_for_spa_path("/login") == "noindex, nofollow"
    assert _robots_tag_for_spa_path("queue") == "noindex, nofollow"
    assert _robots_tag_for_spa_path("/thread/42") == "noindex, nofollow"
    assert _robots_tag_for_spa_path("/some-unknown-route") == "noindex, nofollow"


@pytest.mark.asyncio
async def test_landing_route_has_no_noindex_header(auth_client: AsyncClient) -> None:
    """The indexable landing page must not carry a noindex robots header."""
    response = await auth_client.get("/")
    assert response.status_code == 200
    assert "x-robots-tag" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("path", UTILITY_PATHS + PRIVATE_PATHS)
async def test_non_indexable_routes_emit_noindex_header(
    auth_client: AsyncClient, path: str
) -> None:
    """Utility and private SPA paths must opt out of indexing at the HTTP layer."""
    response = await auth_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.asyncio
async def test_robots_txt_served_as_plain_text(auth_client: AsyncClient) -> None:
    """robots.txt must be served as plain text, never as SPA HTML."""
    response = await auth_client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "public" in response.headers["cache-control"]
    assert "User-agent:" in response.text


@pytest.mark.asyncio
async def test_robots_txt_allows_landing_and_assets(auth_client: AsyncClient) -> None:
    """robots.txt must not accidentally block the landing page or its assets."""
    response = await auth_client.get("/robots.txt")
    assert response.status_code == 200
    body = response.text
    assert re.search(r"(?m)^Allow: /\s*$", body) is not None
    assert "Allow: /assets/" in body
    assert "Allow: /static/" in body
    assert re.search(r"(?m)^Disallow: /\s*$", body) is None


@pytest.mark.asyncio
async def test_robots_txt_disallows_utility_private_and_api(
    auth_client: AsyncClient,
) -> None:
    """robots.txt must keep utility, private, and API paths out of crawls."""
    response = await auth_client.get("/robots.txt")
    assert response.status_code == 200
    body = response.text
    for blocked in (
        "/login",
        "/register",
        "/forgot-password",
        "/reset-password",
        "/demo",
        "/queue",
        "/thread/",
        "/history",
        "/glossary",
        "/identity-inbox",
        "/api/",
    ):
        assert f"Disallow: {blocked}" in body


@pytest.mark.asyncio
async def test_robots_txt_matches_source_policy(auth_client: AsyncClient) -> None:
    """The served policy must equal the version-controlled robots.txt source."""
    assert ROBOTS_SOURCE.exists()
    response = await auth_client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == ROBOTS_SOURCE.read_text()


@pytest.mark.asyncio
async def test_robots_txt_advertises_the_sitemap(auth_client: AsyncClient) -> None:
    """``robots.txt`` must advertise the sitemap with an absolute URL."""
    response = await auth_client.get("/robots.txt")
    assert response.status_code == 200
    assert re.search(r"(?m)^Sitemap: https://\S+/sitemap\.xml\s*$", response.text) is not None


@pytest.mark.asyncio
async def test_sitemap_xml_served_as_xml_not_spa_html(auth_client: AsyncClient) -> None:
    """``/sitemap.xml`` must answer with XML, never the SPA HTML shell."""
    response = await auth_client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "public" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_sitemap_xml_lists_only_indexable_routes(auth_client: AsyncClient) -> None:
    """The served sitemap must list every indexable route and nothing else."""
    response = await auth_client.get("/sitemap.xml")
    assert response.status_code == 200

    locations = _sitemap_locations(response.text)
    assert locations == [f"{PRODUCTION_ORIGIN}/"]
    for path in NON_INDEXABLE_PATHS:
        assert f"{PRODUCTION_ORIGIN}{path}" not in locations


def test_rendered_sitemap_matches_the_canonical_indexable_paths() -> None:
    """The fallback sitemap must mirror ``_SPA_INDEXABLE_PATHS`` exactly."""
    locations = _sitemap_locations(_render_sitemap_xml())
    expected = [f"{PRODUCTION_ORIGIN}{path}" for path in sorted(_SPA_INDEXABLE_PATHS)]
    assert locations == expected


def test_frontend_index_prerenders_crawlable_landing() -> None:
    """The built `/` must contain meaningful HTML before client JS runs.

    Vite carries ``frontend/index.html`` verbatim into the served
    ``static/react/index.html``, so asserting on the source proves a
    production-like request for `/` returns crawlable ComicPile content,
    one stable canonical URL, and a description without executing JavaScript.
    """
    assert FRONTEND_INDEX.exists()
    html = FRONTEND_INDEX.read_text()
    assert "data-prerendered-landing" in html
    assert "A dice-driven reading queue for your comic collection." in html
    assert 'rel="canonical"' in html
    assert html.count('rel="canonical"') == 1
    assert 'name="description"' in html
    assert "<noscript>" in html
