"""Parse and classify recognized ComicVine resource URLs.

The correction flow accepts a pasted ComicVine URL as direct identity
evidence. Only the issue and volume resource forms are supported, and only
the official ``comicvine.gamespot.com`` host is trusted so that arbitrary
hostnames cannot be used to smuggle identity input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

COMICVINE_HOSTS = ("comicvine.gamespot.com", "www.comicvine.gamespot.com")

_RESOURCE_SEGMENT = re.compile(r"^(4000|4050)-(\d+)$")


@dataclass(frozen=True)
class ComicVineUrlMeta:
    """A recognized ComicVine resource referenced by a pasted URL.

    Attributes:
        kind: ``issue`` (``4000-<id>``) or ``volume`` (``4050-<id>``).
        resource_id: The numeric ComicVine resource ID.
        raw: The original pasted input.
    """

    kind: str
    resource_id: int
    raw: str


def parse_comicvine_url(raw: str) -> ComicVineUrlMeta | None:
    """Parse a pasted ComicVine issue or volume URL.

    Accepts forms such as ``https://comicvine.gamespot.com/<slug>/4000-1154070/``
    and ``https://comicvine.gamespot.com/<slug>/4050-148476/``. Query strings,
    trailing slashes, and ``http`` schemes are tolerated. Any other host,
    resource prefix, or malformed URL returns ``None``.

    Args:
        raw: The untrusted pasted input.

    Returns:
        Parsed resource metadata, or ``None`` when the input is not a
        recognized ComicVine issue/volume URL.
    """
    value = raw.strip()
    if not value:
        return None
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    hostname = parts.hostname
    if hostname is None or hostname.lower() not in COMICVINE_HOSTS:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if not segments:
        return None
    match = _RESOURCE_SEGMENT.fullmatch(segments[-1])
    if match is None:
        return None
    prefix, id_part = match.groups()
    return ComicVineUrlMeta(
        kind="issue" if prefix == "4000" else "volume",
        resource_id=int(id_part),
        raw=value,
    )


def looks_like_url(raw: str) -> bool:
    """Return True when the trimmed input is a URL-shaped string.

    Used by the frontend contract so ordinary title search is never routed
    through URL resolution.

    Args:
        raw: The correction input to classify.

    Returns:
        True when the input contains an explicit scheme separator.
    """
    value = raw.strip()
    return bool(value) and ("://" in value or value.lower().startswith("http"))