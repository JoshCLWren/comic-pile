import { useState } from 'react'
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
}

/**
 * One small, accessible entrance to the same issue-specific cover, mapping
 * and direct Read now / Rate / Mark unread card used in Reading Lists.
 *
 * Large issue grids pass their *one batched* card projection in `card`; the
 * trigger requests a card only if a reader expands an entry without a batch.
 * A click never triggers a Roll command, stage an edit, or navigate away.
 * This shared trigger is appropriate for Thread, Queue and creator evidence
 * where rendering the full editor in every row would crowd out the content.
 */
export default function CompactIssueCardTrigger({
  issueId, threadTitle, issueNumber, status = 'unread',
  rating = null, card, onMutated,
}: Props) {
  const [open, setOpen] = useState(false)
  const fetched = useIssueCards([issueId], { enabled: open && card == null })
  const resolved = card ?? fetched.data?.find((item) => item.issue_id === issueId) ?? null
  const title = resolved?.thread_title || threadTitle
  const number = resolved?.issue_number || issueNumber
  const isRead = (resolved?.status ?? status) === 'read'

  return (
    <div className="min-w-0" data-testid={`issue-card-trigger-${issueId}`}>
      <button
        type="button"
        aria-label={`Reading and mapping actions for ${title} #${number}`}
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
          <span className="block break-words text-xs font-semibold">{title} #{number}</span>
          <span className="block text-[11px] text-[var(--theme-text-muted)]">
            {isRead ? 'Read' : 'Unread'}
            {(resolved?.rating ?? rating) != null ? ` · Rated ${resolved?.rating ?? rating}` : ''}
            {' · '}{open ? 'Close actions' : 'Read / Rate / Map'}
          </span>
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {fetched.isError && !card && (
            <div role="alert" className="text-xs text-[var(--theme-danger)]">
              Could not load issue metadata: {getApiErrorDetail(fetched.error)}
              <button type="button" onClick={() => void fetched.refetch()}
                className="ml-2 min-h-9 font-semibold underline">Retry</button>
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
      )}
    </div>
  )
}
