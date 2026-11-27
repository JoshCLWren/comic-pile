import type { CSSProperties, KeyboardEvent, MouseEvent } from 'react'
import CompactIssueCardTrigger from '../../../components/CompactIssueCardTrigger'
import { ComicIssueCover } from '../../../components/ComicIssueCard'
import type { IssueCard } from '../../../services/issueCardsApi'
import type { RollBootstrapThread } from '../../../types/rollBootstrap'

interface RollCoverProps {
  thread: RollBootstrapThread
  /** One-based die face, stable for the lifetime of the current pool. */
  face: number
  card?: IssueCard | null
  /** True for the authoritative winning face after a roll. */
  winner?: boolean
  /** Gallery-only presentation flags. */
  center?: boolean
  far?: boolean
  style?: CSSProperties
  className?: string
  onOpen: () => void
}

/**
 * A single cover-first die face (issue #5981). The exact shared issue-card
 * trigger stays mounted for owned issues so Read/Rate/Map and series actions
 * never fork into a second dialog family; clicking the surrounding cover opens
 * the existing series action sheet. Both surfaces stop propagation into each
 * other, and manual browsing never issues a roll mutation.
 */
export function RollCover({
  thread,
  face,
  card,
  winner = false,
  center = false,
  far = false,
  style,
  className = '',
  onOpen,
}: RollCoverProps) {
  const displayTitle = card?.thread_title ?? thread.title
  const issueNumber = card?.issue_number ?? thread.issue_number
  const tagNames = (thread.tags ?? []).map((tag) => tag.name).filter(Boolean)
  const routeLabels = (thread.route_labels ?? []).filter(Boolean)
  const label = `Die face ${face}: ${displayTitle}${issueNumber ? `, issue ${issueNumber}` : ''}${
    tagNames.length ? `, tagged ${tagNames.join(', ')}` : ''
  }${routeLabels.length ? `, connected to ${routeLabels.join(', ')}` : ''}${
    (thread.overflow_routes_count ?? 0) > 0
      ? `, ${thread.overflow_routes_count} more connected routes`
      : ''
  }. Open series actions.`

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onOpen()
    }
  }

  // The nested shared trigger owns its own click. Letting that click bubble
  // would open the series action sheet behind the issue card and consume a
  // manual read as a pending-offer selection.
  const stopIssueCardClick = (event: MouseEvent<HTMLDivElement>) =>
    event.stopPropagation()
  const stopIssueCardKeyDown = (event: KeyboardEvent<HTMLDivElement>) =>
    event.stopPropagation()

  const classes = [
    'roll-cover',
    winner ? 'roll-cover-winner' : '',
    center ? 'roll-cover-center' : '',
    far ? 'roll-cover-far' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      className={classes}
      style={style}
      data-roll-face={face}
      data-testid="roll-pool-cover"
      role="button"
      tabIndex={far ? -1 : 0}
      aria-label={label}
      aria-pressed={winner}
      onClick={onOpen}
      onKeyDown={handleKeyDown}
    >
      {thread.issue_id != null ? (
        <div
          className="roll-cover-actions"
          onClick={stopIssueCardClick}
          onKeyDown={stopIssueCardKeyDown}
        >
          <CompactIssueCardTrigger
            issueId={thread.issue_id}
            threadTitle={displayTitle}
            issueNumber={issueNumber ?? ''}
            status={card?.status === 'read' ? 'read' : 'unread'}
            card={card ?? null}
            hideTitle
          />
        </div>
      ) : (
        <ComicIssueCover
          coverImageUrl={card?.cover_image_url ?? null}
          threadTitle={displayTitle}
          issueNumber={issueNumber ?? ''}
          variant="compact"
          frameClassName="roll-cover-frame"
          imageClassName="roll-cover-art"
          altText=""
          testId="roll-cover-art"
          placeholderTestId="roll-cover-missing"
        />
      )}
      <span className="roll-cover-face" aria-hidden="true">
        {face}
      </span>
      {card?.status === 'read' ? (
        <span className="roll-cover-read" aria-hidden="true">
          ✓
        </span>
      ) : null}
    </div>
  )
}
