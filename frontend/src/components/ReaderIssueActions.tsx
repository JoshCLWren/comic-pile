import { useState } from 'react'
import { useMoveToFront } from '../hooks/useQueue'
import { useThreadIssuesEffectiveTags } from '../hooks/useTags'
import { useIssueCards } from '../hooks/useIssueCards'
import { getApiErrorDetail } from '../utils/apiError'
import { IssueTagRowChips } from './Tags/IssueTagRowChips'
import { ComicIssueCard } from './ComicIssueCard'
import type { IssueCard } from '../services/issueCardsApi'

/**
 * Direct-read entry point shared by Reading Plans and Reading Lists (#4444).
 *
 * This is the same exact-issue featured experience the header "Read next issue"
 * button opens: cover, identity and rating without an intermediate Roll
 * navigation, writing nothing until Save. Queued Roll offers are unaffected.
 */
export function ReadNowIssueButton({ issueId, threadId: _threadId, label = 'Read now', primary = false, threadTitle, issueNumber }: {
  issueId: number; threadId: number; label?: string; primary?: boolean; threadTitle?: string; issueNumber?: string
}) {
  const [open, setOpen] = useState(false)
  const cards = useIssueCards([issueId], { enabled: open })

  if (open) {
    return (
      <ComicIssueCard
        issueId={issueId}
        card={cards.data?.[0] ?? null}
        threadTitle={threadTitle ?? ''}
        issueNumber={issueNumber ?? ''}
        status={cards.data?.[0]?.status === 'read' ? 'read' : 'unread'}
        variant="featured"
      />
    )
  }

  return (
    <span className="inline-flex flex-col items-start gap-1">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={primary
          ? 'inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black hover:bg-[var(--theme-primary-action-hover)]'
          : 'min-h-11 rounded-lg px-3 text-sm font-bold text-[var(--theme-primary-action)] hover:underline'}
      >
        {label}
      </button>
    </span>
  )
}

/**
 * Issue-level progress and queue actions shared by Reading Plans and Reading
 * Reading Lists. The availability prop is advisory only: blocked, later,
 * excluded or inactive issues keep their full direct controls.
 */
export function ReaderIssueActions({ issueId, threadId, issueNumber, isRead, available, seriesTitle, card }: {
  issueId: number; threadId: number; issueNumber: string; isRead: boolean; available: boolean; seriesTitle?: string; card?: IssueCard | null
}) {
  const fallbackCards = useIssueCards([issueId], { enabled: card === undefined })
  const resolvedCard = card ?? fallbackCards.data?.[0] ?? null
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

  const advisory =
    available
      ? null
      : "Reading list suggests this waits — you can still read it now. Your choice doesn't change the list order."

  return (
    <div className="mt-2 space-y-1">
      {row && <IssueTagRowChips data={row} issueNumber={issueNumber} />}
      {tags.isError && <p className="text-xs text-[var(--theme-text-muted)]">Tags unavailable.</p>}
      <ComicIssueCard
        issueId={issueId}
        card={resolvedCard}
        threadTitle={resolvedCard?.thread_title ?? seriesTitle ?? ''}
        issueNumber={resolvedCard?.issue_number ?? issueNumber}
        status={isRead ? 'read' : 'unread'}
        variant="standard"
        advisory={advisory}
      />
      {available && (
        <button
          type="button"
          disabled={moveToFront.isPending}
          onClick={() => void handleMoveToFront()}
          className="min-h-11 rounded-lg px-3 text-sm font-semibold text-[var(--theme-continuity-accent)] hover:underline disabled:opacity-50"
        >
          {moveToFront.isPending ? 'Moving…' : moved ? 'Moved to front' : 'Move to front'}
        </button>
      )}
      {moveError && <p role="alert" className="text-sm text-[var(--theme-error)]">{moveError}</p>}
    </div>
  )
}
