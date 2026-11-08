import { useEffect, useState } from 'react'
import { ComicIssueCard, ComicIssueCover } from './ComicIssueCard'
import { useIssueCards } from '../hooks/useIssueCards'
import { getApiErrorDetail } from '../utils/apiError'
import type { IssueCard, IssueReadRateResponse } from '../services/issueCardsApi'

interface Props {
  issueId: number
  threadTitle: string
  issueNumber: string
  status?: 'read' | 'unread'
  rating?: number | null
  card?: IssueCard | null
  onMutated?: (response: IssueReadRateResponse) => void
  /** Parent already displays the exact issue name in an adjacent named link. */
  hideTitle?: boolean
  /** Context-specific label for the same covered issue action, e.g. a Plan's next issue. */
  actionLabel?: string
}

/** On-demand detail loader: a dense collapsed list does not mount a query per row. */
function ExpandedIssueCard({
  issueId, card, threadTitle, issueNumber, status, rating, onMutated, onCardLoaded,
}: Omit<Props, 'hideTitle'> & { onCardLoaded: (card: IssueCard) => void }) {
  const fetched = useIssueCards([issueId], { enabled: card == null })
  const fetchedExact = fetched.data?.find((item) => item.issue_id === issueId) ?? null
  useEffect(() => {
    if (fetchedExact) onCardLoaded(fetchedExact)
  }, [fetchedExact, onCardLoaded])
  const resolved = card ?? fetchedExact
  const title = resolved?.thread_title || threadTitle
  const number = resolved?.issue_number || issueNumber
  const isRead = (resolved?.status ?? status) === 'read'

  return (
    <div className="mt-2 space-y-2">
      {fetched.isError && card == null && (
        <div role="alert" className="text-xs text-[var(--theme-danger)]">
          Could not load issue metadata: {getApiErrorDetail(fetched.error)}
          <button
            type="button" onClick={() => void fetched.refetch()}
            className="ml-2 min-h-9 font-semibold underline"
          >Retry</button>
        </div>
      )}
      <ComicIssueCard
        issueId={issueId}
        card={resolved}
        threadTitle={title}
        issueNumber={number}
        status={isRead ? 'read' : 'unread'}
        rating={rating}
        variant="compact"
        onMutated={onMutated}
      />
    </div>
  )
}

/**
 * The shared covered entrance for every exact owned comic issue in a dense row.
 * The owning view provides one bounded batch projection; an absent card is
 * fetched only when the user expands this issue, never per collapsed row.
 * The full action surface is ComicIssueCard, not a separate imitation.
 */
export default function CompactIssueCardTrigger({
  issueId, threadTitle, issueNumber, status = 'unread',
  rating = null, card, onMutated, hideTitle = false, actionLabel,
}: Props) {
  const [open, setOpen] = useState(false)
  const [loadedCard, setLoadedCard] = useState<IssueCard | null>(null)
  // Never let a stale card for a different canonical issue masquerade as this
  // issue if a virtualized list reuses a component position.
  const resolved = (card?.issue_id === issueId ? card : null)
    ?? (loadedCard?.issue_id === issueId ? loadedCard : null)
  const title = resolved?.thread_title || threadTitle
  const number = resolved?.issue_number || issueNumber
  const isRead = (resolved?.status ?? status) === 'read'

  return (
    <div className="min-w-0" data-testid={`issue-card-trigger-${issueId}`}>
      <button
        type="button"
        aria-label={actionLabel ? `${actionLabel}: ${title} #${number}` : `Reading and mapping actions for ${title} #${number}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-11 max-w-full items-center gap-2 rounded-lg p-1 text-left text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
      >
        <ComicIssueCover
          coverImageUrl={resolved?.cover_image_url ?? null}
          threadTitle={title}
          issueNumber={number}
          variant="compact"
        />
        <span className="min-w-0">
          {!hideTitle && <span className="block break-words text-xs font-semibold">{title} #{number}</span>}
          <span className="block text-[11px] text-[var(--theme-text-muted)]">
            {isRead ? 'Read' : 'Unread'}
            {(resolved?.rating ?? rating) != null ? ` · Rated ${resolved?.rating ?? rating}` : ''}
            {' · '}{open ? 'Close actions' : actionLabel ?? 'Read / Rate / Map'}
          </span>
        </span>
      </button>
      {open && (
        <ExpandedIssueCard
          issueId={issueId}
          card={resolved}
          threadTitle={title}
          issueNumber={number}
          status={isRead ? 'read' : 'unread'}
          rating={rating}
          onMutated={onMutated}
          onCardLoaded={setLoadedCard}
        />
      )}
    </div>
  )
}
