import type { ManualCreatorCredit } from '../types'

/**
 * Authoritative rated-comic floor for the reader-facing "Small sample"
 * indicator (#3627, #4237).
 *
 * The creators directory and creator comparison both describe the same
 * confidence concept, so they share this value instead of restating it. The
 * server's `MIN_RATED_FOR_RELIABLE` defines the comparison response's
 * `insufficient_data` flag; `tests/test_creator_comparison_api.py` pins that
 * backend constant at the same 5-rated-item floor.
 */
export const SMALL_SAMPLE_THRESHOLD = 5

/**
 * Get formatted display text for creator credits.
 *
 * @param creators Array of creator credits (optional)
 * @returns Formatted string showing creator names and roles
 */
export function getCreatorDisplayText(
  creators: ManualCreatorCredit[] | null | undefined,
): string {
  const list = creators ?? []
  if (list.length === 0) {
    return ''
  }

  return list
    .map((creator) => {
      if (creator.roles.length === 0) {
        return creator.name
      }
      return `${creator.name} (${creator.roles.join(', ')})`
    })
    .join(' • ')
}
