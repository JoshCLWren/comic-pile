export function isReviewsFeatureEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_REVIEWS === 'true'
}
