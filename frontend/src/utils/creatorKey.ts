/**
 * Canonical creator identity keys (issue #2036 / #2030).
 *
 * Downstream creator analytics and navigation key creators by the stable
 * provider-backed identity ``creator:<external-person-id>``, never by display
 * name. Two people sharing a display name stay distinguishable; a creator row
 * without a stable provider id gets no key and must render as plain text.
 */

const CREATOR_KEY_PREFIX = 'creator'

export function buildCreatorKey(creatorId: number): string {
  return `${CREATOR_KEY_PREFIX}:${creatorId}`
}

/**
 * Parse a canonical creator key into the stable external person id.
 *
 * Returns `null` for any non-canonical shape (role-scoped taste keys,
 * display-name-derived keys, malformed input). Callers must never guess an
 * identity from a name.
 */
export function parseCreatorKey(key: string | null | undefined): number | null {
  if (!key) return null
  const parts = key.split(':')
  if (parts.length !== 2 || parts[0] !== CREATOR_KEY_PREFIX || !/^\d+$/.test(parts[1])) {
    return null
  }
  return Number(parts[1])
}

interface CreatorIdentity {
  creator_id?: number | null
}

/**
 * Resolve the canonical creator key for a ComicVine creator row, or `null`
 * when the row lacks a stable provider id and must remain unlinked.
 */
export function creatorKeyFor(creator: CreatorIdentity | null | undefined): string | null {
  const id = creator?.creator_id
  if (id == null || !Number.isInteger(id)) return null
  return buildCreatorKey(id)
}

/** Route path for a canonical creator key, e.g. `/creators/creator:12345`. */
export function creatorRoutePath(creatorKey: string): string {
  return `/creators/${encodeURIComponent(creatorKey)}`
}
