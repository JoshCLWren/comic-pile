const collectionsFlag = import.meta.env.VITE_ENABLE_COLLECTIONS

export const collectionsEnabled = collectionsFlag === 'true'

export function isReviewsFeatureEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_REVIEWS === 'true'
}
