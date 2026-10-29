import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMoveToFront } from '../hooks/useQueue'
import { useReaderProgress } from '../hooks/useReaderProgress'
import { useThreadIssuesEffectiveTags } from '../hooks/useTags'
import { resetRollBootstrapAfterManualSelection } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { threadsApi } from '../services/api-threads'
import { getApiErrorDetail } from '../utils/apiError'
import { IssueTagRowChips } from './Tags/IssueTagRowChips'

/**
 * Select the exact issue offered by a reading order into the existing pending
 * Roll/rating workflow. An expected issue guard on set-pending rejects a stale
 * frontier instead of silently selecting the next issue of that series.
 */
export function ReadNowIssueButton({ issueId, threadId, label = 'Read now', primary = false }: {
  issueId: number; threadId: number; label?: string; primary?: boolean
}) {
  const navigate = useNavigate()
  const inFlight = useRef(false)
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleReadNow() {
    if (inFlight.current) return
    inFlight.current = true
    setIsPending(true)
    setError(null)
    try {
      const response = await threadsApi.setPending(threadId, issueId)
      await resetRollBootstrapAfterManualSelection(queryClient)
      navigate('/', { state: { rollResponse: response } })
    } catch (reason: unknown) {
      setError(getApiErrorDetail(reason) || 'Could not select this issue. Refresh and try again.')
    } finally {
      inFlight.current = false
      setIsPending(false)
    }
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={() => void handleReadNow()}
        disabled={isPending}
        className={primary
          ? 'inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50'
          : 'min-h-11 rounded-lg px-3 text-sm font-bold text-[var(--theme-primary-action)] hover:underline disabled:opacity-50'}
      >
        {isPending ? 'Selecting…' : label}
      </button>
      {error && <span role="alert" className="max-w-xs text-xs text-[var(--theme-danger)]">{error}</span>}
    </span>
  )
}

/** Issue-level progress and queue actions shared by Reading Plans and Reading Lists. */
export function ReaderIssueActions({ issueId, threadId, issueNumber, isRead, available }: {
  issueId: number; threadId: number; issueNumber: string; isRead: boolean; available: boolean
}) {
  const progress = useReaderProgress(issueId, isRead)
  const moveToFront = useMoveToFront()
  const [moveError, setMoveError] = useState<string | null>(null)
  const [moved, setMoved] = useState(false)
  const tags = useThreadIssuesEffectiveTags(threadId)
  const row = tags.data?.issues.find((item) => item.target_id === issueId)

  async function handleMoveToFront() {
    setMoveError(null)
    setMoved(false)
    try {
      await moveToFront.mutate(threadId)
      setMoved(true)
    } catch (reason: unknown) {
      setMoveError(getApiErrorDetail(reason) || 'Unable to move this series to the front.')
    }
  }

  return (
    <div className="mt-2 space-y-1">
      {row && <IssueTagRowChips data={row} issueNumber={issueNumber} />}
      {tags.isError && <p className="text-xs text-[var(--theme-text-muted)]">Tags unavailable.</p>}
      <div className="flex flex-wrap items-start gap-1">
        {available && (
          <>
            <ReadNowIssueButton issueId={issueId} threadId={threadId} />
            <button
              type="button"
              disabled={moveToFront.isPending}
              onClick={() => void handleMoveToFront()}
              className="min-h-11 rounded-lg px-3 text-sm font-semibold text-[var(--theme-continuity-accent)] hover:underline disabled:opacity-50"
            >
              {moveToFront.isPending ? 'Moving…' : moved ? 'Moved to front' : 'Move to front'}
            </button>
          </>
        )}
        {(isRead || available) && (
          <button
            type="button"
            onClick={() => progress.mutate()}
            disabled={progress.isPending}
            className="min-h-11 rounded-lg px-3 text-sm font-semibold text-[var(--theme-primary-action)] disabled:opacity-50"
          >
            {progress.isPending ? 'Saving…' : isRead ? 'Mark unread' : 'Mark read'}
          </button>
        )}
      </div>
      {moveError && <p role="alert" className="text-sm text-[var(--theme-danger)]">{moveError}</p>}
      {progress.isError && <p role="alert" className="text-sm text-[var(--theme-danger)]">Unable to update this issue. Try again.</p>}
    </div>
  )
}
