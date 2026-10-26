import { useState } from 'react'
import { rateApi } from '../../services/api-rate'
import type { Issue } from '../../types'

interface IssueRateButtonProps {
  issue: Issue
  threadId: number
}

const RATING_VALUES = [0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]

/** Rate an issue directly from its Thread row without launching Roll (issue #3581). */
export function IssueRateButton({ issue, threadId }: IssueRateButtonProps) {
  const [open, setOpen] = useState(false)
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(rating: number) {
    setIsPending(true)
    setError(null)
    try {
      await rateApi.rate({
        thread_id: threadId,
        rating,
        direct: true,
        issue_number: issue.issue_number,
      })
      setOpen(false)
    } catch {
      setError('Failed to rate')
    } finally {
      setIsPending(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      {error && <span className="text-xs text-red-400">{error}</span>}
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={isPending}
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
              onClick={() => void submit(value)}
              disabled={isPending}
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
