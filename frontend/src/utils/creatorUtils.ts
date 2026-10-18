import type { ManualCreatorCredit } from '../types'

/**
 * Get formatted display text for creator credits.
 * 
 * @param creators Array of creator credits
 * @returns Formatted string showing creator names and roles
 */
export function getCreatorDisplayText(creators: ManualCreatorCredit[]): string {
  if (creators.length === 0) {
    return ''
  }

  return creators.map(creator => {
    if (creator.roles.length === 0) {
      return creator.name
    }
    return `${creator.name} (${creator.roles.join(', ')})`
  }).join(' • ')
}