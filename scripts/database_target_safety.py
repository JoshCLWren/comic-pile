"""Safety checks for commands that may mutate a development database."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse


_LOCAL_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})
_CI_LOCAL_HOSTNAME = "postgres"


def require_local_database_url(db_url: str) -> None:
    """Reject database URLs unless their host is provably local.

    Args:
        db_url: PostgreSQL connection URL that a mutating command intends to use.

    Returns:
        None when the URL targets a loopback host or the CI-local PostgreSQL service.

    Raises:
        ValueError: If the URL is malformed, has no host, or targets a non-local host.
    """
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname
    except ValueError as error:
        raise ValueError("Import database URL is malformed; refusing to write") from error

    if not host:
        raise ValueError("Import database URL has no host; refusing to write")

    normalized_host = host.rstrip(".").lower()
    if normalized_host in _LOCAL_HOSTNAMES:
        return
    if normalized_host == _CI_LOCAL_HOSTNAME and os.getenv("CI") == "true":
        return

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError as error:
        raise ValueError(
            f"Import database host {host!r} is not loopback/local; refusing to write"
        ) from error

    if not address.is_loopback:
        raise ValueError(
            f"Import database host {host!r} is not loopback/local; refusing to write"
        )
