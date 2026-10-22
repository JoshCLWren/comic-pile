"""Canonical Comic Vine volume identity keys for reader-approved overlap choices.

A reader-approved overlap decision names two exact Comic Vine volumes. The
canonical key is ``comicvine:<external id>`` so a stored choice can never be
matched to another provider's identity, to a free-text series name, or to a
same-titled other volume. Comic Vine's numeric volume identifiers are
normalized exactly as the collection-exclusion guard normalizes them, so the
same volume always produces the same key.
"""

from __future__ import annotations

import re

from app.services.collection_exclusion_guard import normalize_volume

#: The only provider whose volume identities may back an overlap decision.
COMICVINE_PROVIDER = "comicvine"

#: External identities of this entity type are Comic Vine volumes (series).
VOLUME_ENTITY_TYPE = "series"

#: Accepted shape of a client-supplied canonical volume key.
VOLUME_KEY_PATTERN = re.compile(r"^comicvine:[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def volume_identity_key(external_id: str) -> str:
    """Return the canonical key naming one exact Comic Vine volume.

    Args:
        external_id: Provider external identifier of the volume.

    Returns:
        Canonical ``comicvine:<external id>`` key.
    """
    return f"{COMICVINE_PROVIDER}:{external_id}"


def canonical_volume_key(provider: str, external_id: str) -> str | None:
    """Return the canonical key for a stored provider identity, or None.

    Args:
        provider: Provider that owns the identity.
        external_id: Provider external identifier of the identity.

    Returns:
        Canonical volume key for Comic Vine series identities, otherwise None
        because only Comic Vine volumes may back an overlap decision.
    """
    normalized_provider, normalized_id = normalize_volume(provider, external_id)
    if normalized_provider != COMICVINE_PROVIDER:
        return None
    return volume_identity_key(normalized_id)


def parse_volume_identity_key(key: str) -> str | None:
    """Return the Comic Vine external ID named by a canonical key, or None.

    Args:
        key: Client-supplied canonical volume key.

    Returns:
        External ID named by the key, or None when the key does not name
        exactly one Comic Vine volume.
    """
    if not VOLUME_KEY_PATTERN.match(key):
        return None
    return key.split(":", 1)[1]


def normalized_volume_key(key: str) -> str | None:
    """Return the normalized canonical key for a client-supplied key, or None.

    Args:
        key: Client-supplied canonical volume key.

    Returns:
        Canonical key using the normalized Comic Vine external ID, or None when
        the key does not name exactly one Comic Vine volume.
    """
    external_id = parse_volume_identity_key(key)
    if external_id is None:
        return None
    return canonical_volume_key(COMICVINE_PROVIDER, external_id)
