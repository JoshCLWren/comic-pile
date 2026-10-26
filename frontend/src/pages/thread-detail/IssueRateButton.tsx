import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { rateApi } from '../../services/api-rate'
import type { Issue } from '../../types'
import { queryClient } from '../../query/queryClient'
import { applyRatedThreadCache } from '../../query/cacheEffects'

interface IssueRateButtonProps {
  issue: Issue
  threadId: number
}

const RATING_VALUES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/** Rate an issue directly from its Thread row without launching Roll (issue #3581). */
export function IssueRateButton({ issue, threadId }: IssueRateButtonProps) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (rating: number) =>
      rateApi.rate({
        thread_id: threadId,
        rating,
        direct: true,
        issue_number: issue.issue_number,
      }),
    onMutate: () => {
      setError(null)
    },
    onSuccess: async (thread) => {
      await applyRatedThreadCache(queryClient, thread)
      setOpen(false)
    },
    onError: () => {
      setError('Failed to rate')
    },
  })

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-red-400">{error}</span>}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={mutation.isPending}
        className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 disabled:opacity-50"
      >
        Rate
      </button>
      {open && (
        <div className="flex flex-wrap gap-1">
          {RATING_VALUES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => mutation.mutate(value)}
              disabled={mutation.isPending}
              className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 disabled:opacity-50"
            >
              {value}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
