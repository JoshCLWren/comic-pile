import { useCallback, useEffect, useState } from 'react'
import ReadingModeQuiz from './ReadingModeQuiz'
import {
  dismissReadingModeSuggestion,
  getReadingMode,
} from '../services/readingMode'
import { FEATURES } from '../config/features'
import type { ReadingModeState } from '../types'

/**
 * Always-reachable entry point for the reading-mode quiz plus a non-blocking
 * suggestion when a low-confidence/mismatch flow has flagged the session. The
 * quiz never opens automatically and never blocks rolling.
 */
export default function ReadingModeLauncher() {
  const [mode, setMode] = useState<ReadingModeState | null>(null)
  const [quizOpen, setQuizOpen] = useState(false)
  const [dismissing, setDismissing] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const state = await getReadingMode()
      setMode(state)
    } catch {
      // Reading mode is optional; ignore transient fetch failures.
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleComplete = useCallback((state: ReadingModeState) => {
    setMode(state)
  }, [])

  const handleDismiss = useCallback(async () => {
    setDismissing(true)
    try {
      const state = await dismissReadingModeSuggestion()
      setMode(state)
    } catch {
      // Best-effort dismissal; ignore failures.
    } finally {
      setDismissing(false)
    }
  }, [])

  // Product-surface gate (issue #1945): the quiz persists its result and the
  // weighting machinery exists, but the production Roll path does not yet
  // consume the quiz-selected mode, so the launcher would be misleading. The
  // component, API, persistence, and tests remain available for later
  // completion; flipping FEATURES.readingModeQuiz restores it.
  if (!FEATURES.readingModeQuiz) return null

  const showSuggestion = mode?.suggested === true && !mode.source

  return (
    <div className="px-3 md:px-4">
      <button
        type="button"
        onClick={() => setQuizOpen(true)}
        data-testid="open-reading-mode-quiz"
        className="text-sm text-[var(--theme-comic-accent)] underline-offset-2 hover:underline"
      >
        Find my reading mode
      </button>

      {showSuggestion && (
        <div
          role="status"
          data-testid="reading-mode-suggestion"
          className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-[var(--theme-comic-accent)]/40 bg-[var(--theme-comic-accent)]/10 px-3 py-2 text-sm text-[var(--theme-comic-accent)]"
        >
          <span>Not sure what to read? Let the quiz pick a mode.</span>
          <button
            type="button"
            onClick={() => setQuizOpen(true)}
            data-testid="reading-mode-suggestion-take"
            className="rounded-md bg-[var(--theme-primary-action)] px-2 py-1 font-bold text-[var(--theme-primary-action-text)]"
          >
            Take the quiz
          </button>
          <button
            type="button"
            onClick={handleDismiss}
            disabled={dismissing}
            data-testid="reading-mode-suggestion-dismiss"
            className="rounded-md border border-[var(--theme-comic-accent)]/40 px-2 py-1 text-[var(--theme-comic-accent)] hover:border-[var(--theme-comic-accent)]"
          >
            Not now
          </button>
        </div>
      )}

      <ReadingModeQuiz
        isOpen={quizOpen}
        onClose={() => setQuizOpen(false)}
        onComplete={handleComplete}
      />
    </div>
  )
}
