import type { ManualCreatorCredit } from '../types'

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
