"""Bootstrap alias telemetry for the Roll cutover deprecation gate (issue #2718).

Production must distinguish calls to the three Roll bootstrap surfaces:

- ``/api/roll/bootstrap``  — legacy unversioned alias (``legacy``);
- ``/api/v1/roll/bootstrap`` — canonical v1 alias (``v1``);
- ``/api/v2/roll/bootstrap`` — the v2 projection (``v2``).

For each alias the telemetry records whether the caller looked like a
web-origin (browser) client, so the later 7-day zero-web-origin deletion gate
(#2718/#3040) can be measured from fleetwide aggregates. Only classification
facts are stored: header values, query strings, payloads, and user identities
are never retained. The process-local counter follows the safe, cardinality-
bounded shape of :mod:`app.traffic_metrics` so a collector can merge instances
by keeping the maximum count per key across polls.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

BootstrapAlias = Literal["legacy", "v1", "v2"]

_LEGACY_BOOTSTRAP_PATH: Final[str] = "/api/roll/bootstrap"
_V1_BOOTSTRAP_PATH: Final[str] = "/api/v1/roll/bootstrap"
_V2_BOOTSTRAP_PATH: Final[str] = "/api/v2/roll/bootstrap"

_WEB_ORIGIN_SITES: Final[frozenset[str]] = frozenset(
    {"same-origin", "same-site", "cross-site"}
)

_lock: Final = threading.Lock()
_counts: Final[dict[tuple[BootstrapAlias, bool, str], int]] = {}


def classify_bootstrap_alias(path: str) -> BootstrapAlias | None:
    """Classify a request path as one of the Roll bootstrap aliases.

    Query strings and fragments are ignored; the path still must equal one of
    the three mounted bootstrap routes exactly (no trailing-slash variant is
    matched), so unrelated roll paths and look-alike paths are never counted.

    Args:
        path: Raw request path, e.g. ``request.url.path``.

    Returns:
        ``"legacy"``, ``"v1"``, or ``"v2"``, or ``None`` when not a bootstrap.
    """
    clean = path.split("?", 1)[0].split("#", 1)[0]
    if clean == _LEGACY_BOOTSTRAP_PATH:
        return "legacy"
    if clean == _V1_BOOTSTRAP_PATH:
        return "v1"
    if clean == _V2_BOOTSTRAP_PATH:
        return "v2"
    return None


def _is_web_url(value: str) -> bool:
    """Return whether a header value parses as an http(s) URL.

    Args:
        value: Raw header value.

    Returns:
        True only for ``http``/``https`` scheme URLs with an authority.
    """
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


@dataclass(frozen=True, slots=True)
class BootstrapOriginInfo:
    """Origin/client classification facts for one request.

    Attributes:
        web_origin: Whether the request carried standard browser origin
            signals (``Origin``/``Referer`` web URL or any browser
            ``Sec-Fetch-Site`` value, including ``none`` for direct browser
            navigation). Non-browser clients such as plain curl without these
            headers classify as ``False``.
        cross_origin: Whether the request additionally looked like a cross-site
            browser request, either via ``Sec-Fetch-Site: cross-site`` or an
            ``Origin`` whose host differs from ``Host``. ``False`` when
            cross-origin-ness cannot be determined from the headers.
    """

    web_origin: bool
    cross_origin: bool = False


def classify_web_origin(
    headers: Mapping[str, str], *, host: str | None = None
) -> BootstrapOriginInfo:
    """Classify the browser origin signals of a request from its headers.

    Only derived facts are returned; header values are inspected transiently
    and never stored or logged. ``Sec-Fetch-Site: none`` (browser request with
    no initiator origin, e.g. address-bar navigation) still counts as a
    web-origin client because browser UI depends on those calls too.

    Args:
        headers: Request headers (case-insensitive mapping).
        host: The request's ``Host`` authority used for cross-origin
            comparison; when omitted, host-based cross checks are skipped.

    Returns:
        BootstrapOriginInfo with the derived classification.
    """
    site = (headers.get("Sec-Fetch-Site") or "").strip().lower()

    origin_value = (headers.get("Origin") or "").strip()
    origin_is_web = origin_is_cross = False
    if origin_value and _is_web_url(origin_value):
        origin_is_web = True
        if host:
            origin_host = urlsplit(origin_value).netloc
            if origin_host and origin_host.split("@")[-1] != host.split("@")[-1]:
                origin_is_cross = True

    referer_value = (headers.get("Referer") or "").strip()
    referer_is_web = bool(referer_value) and _is_web_url(referer_value)

    web_origin = (
        origin_is_web or referer_is_web or site in _WEB_ORIGIN_SITES or site == "none"
    )
    cross_origin = origin_is_cross or site == "cross-site"
    return BootstrapOriginInfo(web_origin=web_origin, cross_origin=cross_origin)


@dataclass(frozen=True, slots=True)
class BootstrapAliasCounter:
    """One aggregated (alias, web-origin classification, status class) tally."""

    alias: str
    web_origin: bool
    status_class: str
    count: int


def record_bootstrap_alias_hit(
    alias: BootstrapAlias,
    web_origin: bool,
    status_code: int,
) -> None:
    """Record one completed bootstrap alias call and log its classification.

    Structured telemetry emits a stable, greppable message so fleet log
    aggregation can distinguish the three aliases and the web-origin share.
    The message never includes request identity, path variants, headers, or
    payloads — only the classification facts.

    Args:
        alias: Classified alias from :func:`classify_bootstrap_alias`.
        web_origin: Browser-origin classification from :func:`classify_web_origin`.
        status_code: Response status code returned to the client.
    """
    status_class = f"{status_code // 100}xx"
    with _lock:
        key = (alias, web_origin, status_class)
        _counts[key] = _counts.get(key, 0) + 1
    logger.info(
        "roll.bootstrap.alias.telemetry",
        extra={
            "bootstrap_alias": alias,
            "web_origin": web_origin,
            "status_class": status_class,
        },
    )


def bootstrap_alias_snapshot() -> list[BootstrapAliasCounter]:
    """Return the current process-local alias classification tally.

    Returns:
        Deterministically sorted aggregated counts per
        (alias, web_origin, status class).
    """
    with _lock:
        return [
            BootstrapAliasCounter(
                alias=alias, web_origin=web_origin, status_class=status_class, count=count
            )
            for (alias, web_origin, status_class), count in sorted(_counts.items())
        ]


def reset_bootstrap_alias_counters_for_tests() -> None:
    """Clear every alias counter. Intended for test isolation only."""
    with _lock:
        _counts.clear()
