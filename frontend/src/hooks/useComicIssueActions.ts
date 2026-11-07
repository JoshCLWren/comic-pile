import { useLayoutEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { applyIssueCardMutation } from '../query/cacheEffects'
import {
  issueCardsApi,
  newDirectIssueKey,
  type IssueReadRateResponse,
} from '../services/issueCardsApi'

export interface ComicIssueActionInput {
  /** Explicit new status. Omit for a rating-only correction. */
  status?: 'read' | 'unread'
  /** Effective rating in 0.5-point steps. Omit to keep the stored rating. */
  rating?: number
}

/**
 * One shared direct-issue write path for every manual action (#4444).
 *
 * Read now, Rate / Mark read, Edit rating and Mark unread all go to the same
 * authenticated native command with `source: 'direct'` — never the Roll
 * pending-selection flow, never an eligibility gate. Each intent owns an
 * idempotency key: a retry of the same unanswered intent replays its key so
 * the server returns the original receipt instead of writing a second event.
 */
export function useComicIssueActions(
  issueId: number,
  options?: { onMutated?: (response: IssueReadRateResponse) => void },
) {
  const client = useQueryClient()
  const onMutatedRef = useRef(options?.onMutated)
  useLayoutEffect(() => {
    onMutatedRef.current = options?.onMutated
  }, [options?.onMutated])
  // One in-flight intent per card; kept across the await so Cancel-then-retry
  // reuses the key while a different payload starts a fresh intent.
  const unresolvedRef = useRef<{ status?: 'read' | 'unread'; rating?: number; key: string } | null>(null)

  const mutation = useMutation({
    mutationFn: (input: ComicIssueActionInput) => {
      const previous = unresolvedRef.current
      const key =
        previous && previous.status === input.status && previous.rating === input.rating
          ? previous.key
          : newDirectIssueKey()
      unresolvedRef.current = { status: input.status, rating: input.rating, key }
      return issueCardsApi.patchIssue(issueId, { status: input.status, rating: input.rating, idempotencyKey: key })
    },
    onSuccess: async (response) => {
      unresolvedRef.current = null
      await applyIssueCardMutation(client, response)
      onMutatedRef.current?.(response)
    },
    onError: () => {
      // Keep the key: an ambiguous network outcome may have applied server-side,
      // and the retry must replay the same intent.
    },
  })

  return {
    mutation,
    isPending: mutation.isPending,
    isError: mutation.isError,
    error: mutation.error,
    reset: mutation.reset,
    /** Mark the exact issue read and save the rating in one direct write. */
    markReadAndRate: (rating: number) => mutation.mutateAsync({ status: 'read', rating }),
    /** Correct the rating alone; read state is left untouched. */
    updateRating: (rating: number) => mutation.mutateAsync({ rating }),
    /** Mark the exact issue unread (explicit correction, not a reopen). */
    markUnread: () => mutation.mutateAsync({ status: 'unread' }),
  }
}

export type UseComicIssueActions = ReturnType<typeof useComicIssueActions>
