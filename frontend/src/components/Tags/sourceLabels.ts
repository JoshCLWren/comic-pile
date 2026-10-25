import type { InheritanceSource } from '../../services/api-tags'

/**
 * Reader-facing label for one inherited-tag source (issues #3431, #3557).
 *
 * The backend polymorphic target type is an internal identifier, so it never
 * reaches the reader: `ContinuityPlan` renders as "Reading plan", threads and
 * issues get their own human nouns, and any unmapped type falls back to a
 * neutral "Source" label that still carries the display name. The fallback is
 * deliberately independent of the raw type string so a future backend type
 * cannot leak into the reader-facing source chooser.
 *
 * Args:
 *   source: One inheritance source returned by the effective-tags API.
 *
 * Returns:
 *   A human-readable label such as `Reading plan: Mignolaverse`.
 */
export function sourceLabel(source: InheritanceSource): string {
  const name = source.display_name.trim() || `#${source.target_id}`
  switch (source.target_type) {
    case 'Thread':
      return `Thread: ${name}`
    case 'ContinuityPlan':
      return `Reading plan: ${name}`
    case 'Issue':
      return name.startsWith('#') ? `Issue ${name}` : `Issue #${name}`
    default:
      return `Source: ${name}`
  }
}
