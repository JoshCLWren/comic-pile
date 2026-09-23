import { useQuery } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import Modal from './Modal'
import { queryKeys } from '../query/queryKeys'
import { tasksApi } from '../services/api'
import type { SessionModeUpdateRequest } from '../types'
import type { TopRatedThread } from '../types'

export type CorrectionChoiceId =
  | 'even_easier'
  | 'keep_level_different'
  | 'something_familiar'
  | 'something_different'
  | 'pure_random'

interface CorrectionSheetProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (choice: CorrectionChoiceId, patch: SessionModeUpdateRequest) => Promise<void>
  onOpenQuiz?: () => void
  quizEnabled?: boolean
  /** Optional injected rated history for tests; when provided no network request is made. */
  ratedHistory?: TopRatedThread[] | null
}

interface CorrectionChoiceMeta {
  id: CorrectionChoiceId
  label: string
  description: string
  patch: SessionModeUpdateRequest
}

const CHOICES: CorrectionChoiceMeta[] = [
  {
    id: 'even_easier',
    label: 'Give me something lighter',
    description: 'Favor a lower-commitment, easier read next.',
    patch: { bandwidth: 'light' },
  },
  {
    id: 'keep_level_different',
    label: 'Keep about the same effort',
    description: 'Keep the current commitment, but choose another comic.',
    patch: { intent: 'balanced' },
  },
  {
    id: 'something_familiar',
    label: 'Stay close to what I\u2019ve liked',
    description: 'Favor something similar to comics you\u2019ve rated well.',
    patch: { intent: 'familiar' },
  },
  {
    id: 'something_different',
    label: 'Give me a change of pace',
    description: 'Favor something meaningfully different from recent and high-rated reads.',
    patch: { intent: 'explore' },
  },
  {
    id: 'pure_random',
    label: 'Surprise me',
    description: 'Don\u2019t steer by similarity or effort preference for this reroll.',
    patch: { intent: 'random' },
  },
]

/** Derive a single compact example per choice from the user's own rated history. */
export function deriveCorrectionExamples(
  ratedThreads: TopRatedThread[] | null | undefined,
): Record<CorrectionChoiceId, string | null> {
  const fallback: Record<CorrectionChoiceId, string | null> = {
    even_easier: null,
    keep_level_different: null,
    something_familiar: null,
    something_different: null,
    pure_random: null,
  }
  if (!ratedThreads || ratedThreads.length === 0) return fallback

  // Rated threads are already filtered to >=4.0 and sorted high->low.
  // For effort we sort by issues_remaining when available.
  const withEffort = ratedThreads.filter((t) => typeof t.issues_remaining === 'number')
  const sortedByEffort = [...(withEffort.length > 0 ? withEffort : ratedThreads)].sort(
    (a, b) => (a.issues_remaining ?? 999) - (b.issues_remaining ?? 999),
  )
  const sortedByRating = [...ratedThreads]

  const lightest = sortedByEffort[0] ?? null
  const medianEffort =
    sortedByEffort.length >= 3
      ? sortedByEffort[Math.floor(sortedByEffort.length / 2)]
      : sortedByEffort[1] ?? lightest
  const familiar = sortedByRating[0] ?? null
  // For change-of-pace, prefer the lowest-rated among the high-rated set to illustrate contrast.
  const different = ratedThreads.length >= 2 ? ratedThreads[ratedThreads.length - 1] : null
  // Surprise is illustrative/random — pick a different title than familiar when possible.
  const surpriseSource =
    ratedThreads.length >= 2 ? ratedThreads[1] : (ratedThreads[0] ?? null)

  return {
    even_easier: lightest ? `Think more like \u201C${lightest.title}\u201D` : null,
    keep_level_different: medianEffort ? `Think more like \u201C${medianEffort.title}\u201D` : null,
    something_familiar: familiar ? `Based on your ratings, think more \u201C${familiar.title}\u201D territory` : null,
    something_different:
      different && different.id !== familiar?.id
        ? `Unlike \u201C${familiar?.title}\u201D, try more like \u201C${different.title}\u201D`
        : null,
    pure_random: surpriseSource ? `Illustrative \u2014 e.g. \u201C${surpriseSource.title}\u201D (random, no preference applied)` : null,
  }
}

/**
 * Correction sheet surfaced after meaningful Snooze prediction failures.
 *
 * Each choice maps to the canonical session-mode patch (bandwidth/intent).
 * Copy is plain language answering "What should change about the next roll?"
 * with a subordinate example drawn from the user's own rated history.
 * Examples are explanatory only and never become hard selection constraints.
 */
export default function CorrectionSheet({
  isOpen,
  onClose,
  onSubmit,
  onOpenQuiz,
  quizEnabled = false,
  ratedHistory,
}: CorrectionSheetProps) {
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const shouldFetch = isOpen && ratedHistory === undefined
  const { data: analyticsData } = useQuery({
    queryKey: queryKeys.analytics.overview(),
    queryFn: () => tasksApi.getMetrics(),
    enabled: shouldFetch,
  })
  const ratedThreads = useMemo(() => {
    if (ratedHistory !== undefined) return ratedHistory
    return analyticsData?.top_rated_threads ?? null
  }, [ratedHistory, analyticsData])

  const examples = useMemo(() => deriveCorrectionExamples(ratedThreads), [ratedThreads])

  const handleChoice = useCallback(
    async (choice: CorrectionChoiceMeta) => {
      setSubmitting(true)
      setSubmitError(null)
      try {
        await onSubmit(choice.id, choice.patch)
        onClose()
      } catch (_err) {
        setSubmitError('Failed to update reading mode. Please try again.')
      } finally {
        setSubmitting(false)
      }
    },
    [onSubmit, onClose],
  )

  const handleOpenQuiz = useCallback(() => {
    if (!onOpenQuiz) return
    onClose()
    onOpenQuiz()
  }, [onClose, onOpenQuiz])

  if (!isOpen) return null

  return (
    <Modal isOpen title="Not feeling it?" onClose={onClose} data-testid="correction-sheet">
      <p className="text-sm text-[var(--theme-text-muted)] mb-3" data-testid="correction-sheet-subtitle">
        What should change about the next roll?
      </p>
      {submitError && (
        <p role="alert" className="text-sm text-[var(--theme-danger)]" data-testid="correction-sheet-error">
          {submitError}
        </p>
      )}

      <fieldset className="space-y-3">
        <legend className="sr-only">Pick what should change about the next roll</legend>
        {CHOICES.map((choice) => {
          const example = examples[choice.id]
          const isSurprise = choice.id === 'pure_random'
          return (
            <button
              key={choice.id}
              type="button"
              data-testid={`correction-choice-${choice.id}`}
              disabled={submitting}
              onClick={() => handleChoice(choice)}
              className="w-full text-left rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 transition-colors hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)] disabled:opacity-50"
            >
              <span className="block text-sm font-semibold text-[var(--theme-text-primary)]">{choice.label}</span>
              <span className="block text-xs text-[var(--theme-text-muted)] mt-0.5">{choice.description}</span>
              {example ? (
                <span
                  className="block text-xs text-[var(--theme-text-dim)] mt-1.5"
                  data-testid={`correction-example-${choice.id}`}
                >
                  {example}
                </span>
              ) : isSurprise ? (
                <span
                  className="block text-xs text-[var(--theme-text-dim)] mt-1.5"
                  data-testid={`correction-example-${choice.id}`}
                >
                  No preference signal applied
                </span>
              ) : null}
            </button>
          )
        })}
      </fieldset>

      <div className="mt-4 pt-3 border-t border-[var(--theme-border)]">
        <button
          type="button"
          data-testid="correction-sheet-dismiss"
          disabled={submitting}
          onClick={onClose}
          className="w-full py-2 text-left text-sm font-bold uppercase tracking-wider text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] disabled:opacity-50"
        >
          Dismiss
        </button>
        {quizEnabled && (
          <button
            type="button"
            data-testid="correction-sheet-open-quiz"
            disabled={submitting}
            onClick={handleOpenQuiz}
            className="w-full py-2 text-left text-sm font-bold uppercase tracking-wider text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-comic-accent)] disabled:opacity-50"
          >
            Not sure? Take the two-question quiz
          </button>
        )}
      </div>
    </Modal>
  )
}
