/**
 * Runtime feature flags for the ComicPile frontend.
 *
 * Flags resolve once at build time from `VITE_FEATURE_*` environment variables.
 * Every flag defaults to a safe production state: an unset flag never exposes
 * an unfinished or untrustworthy surface, and restoring a gated surface is a
 * single env flip plus the restoration gate in its owning issue.
 */

function readBool(raw: string | undefined, fallback: boolean): boolean {
  if (raw === undefined || raw === null || raw === '') {
    return fallback
  }
  return raw === 'true' || raw === '1'
}

export const FEATURES = {
  /**
   * Surface the "Find my reading mode" quiz launcher and its suggestion prompts
   * on the production Roll surface.
   *
   * Disabled by default: the quiz persists `reading_bandwidth` / `reading_intent`
   * and the weighting machinery exists, but the production Roll endpoint does not
   * yet consume the quiz-selected mode, so the launcher is misleading. See issue
   * #1945 for the restoration gate. The launcher component, API, persistence, and
   * tests all remain available in code.
   */
  readingModeQuiz: readBool(import.meta.env.VITE_FEATURE_READING_MODE_QUIZ, false),
} as const

declare global {
  interface Window {
    __COMIC_PILE_FEATURES__?: typeof FEATURES
  }
}

if (typeof window !== 'undefined') {
  window.__COMIC_PILE_FEATURES__ = FEATURES
}
