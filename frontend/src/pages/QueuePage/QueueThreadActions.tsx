import Tooltip from '../../components/Tooltip'

interface QueueThreadActionsProps {
  title: string
  snoozeIcon: string
  snoozeLabel: string
  snoozeDisabled: boolean
  readDisabled?: boolean
  readDisabledReason?: string
  onRead: () => void
  onEdit: () => void
  onSnooze: () => void
  onDelete: () => void
}

export default function QueueThreadActions({
  title,
  snoozeIcon,
  snoozeLabel,
  snoozeDisabled,
  readDisabled = false,
  readDisabledReason,
  onRead,
  onEdit,
  onSnooze,
  onDelete,
}: QueueThreadActionsProps) {
  const stopCardClick = (action: () => void) => (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    action()
  }

  // Enable rule: snooze is only available for the pending thread
  // (session.pending_thread_id) — the comic currently waiting to be read — or
  // for already-snoozed threads via Unsnooze. See QueuePage.tsx snoozeDisabled.
  const snoozeTooltip = snoozeDisabled
    ? 'Only the comic currently waiting to be read can be snoozed.'
    : snoozeLabel === 'Unsnooze'
      ? 'Unsnooze to return this comic to the rolling pool.'
      : 'Snooze to temporarily exclude this comic from rolling.'

  const snoozeDescriptionId = `snooze-description-${title.replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase() || 'thread'}`

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label={`Actions for ${title}`}
    >
      {readDisabled ? (
        <Tooltip content={readDisabledReason ?? 'Blocked by dependency'}>
          <button
            type="button"
            aria-label="Read"
            disabled
            title={readDisabledReason ?? 'Blocked by dependency'}
            onClick={(event: React.MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
            className="inline-flex h-11 md:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)]/25 px-4 text-sm font-bold text-white/60 hover:bg-[var(--theme-primary-action)]/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Read
          </button>
        </Tooltip>
      ) : (
        <button
          type="button"
          aria-label="Read"
          onClick={stopCardClick(onRead)}
          className="inline-flex h-11 md:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)] transition-colors"
        >
          Read
        </button>
      )}
      <button
        type="button"
        aria-label="Edit"
        onClick={stopCardClick(onEdit)}
        className="inline-flex h-11 md:h-9 items-center justify-center rounded-lg bg-white/5 px-3 text-sm font-semibold text-[var(--theme-text-muted)] hover:bg-white/10 hover:text-[var(--theme-text-primary)] transition-colors"
      >
        Edit
      </button>
      <Tooltip content={snoozeTooltip}>
        <button
          type="button"
          aria-label={snoozeLabel}
          aria-disabled={snoozeDisabled || undefined}
          aria-describedby={snoozeDisabled ? snoozeDescriptionId : undefined}
          title={snoozeTooltip}
          tabIndex={snoozeDisabled ? 0 : undefined}
          onClick={
            snoozeDisabled
              ? (event: React.MouseEvent<HTMLButtonElement>) => event.stopPropagation()
              : stopCardClick(onSnooze)
          }
          className={`inline-flex h-11 md:h-9 items-center justify-center gap-1.5 rounded-lg bg-white/5 px-3 text-sm font-semibold text-[var(--theme-text-muted)] hover:bg-white/10 hover:text-[var(--theme-text-primary)] transition-colors ${snoozeDisabled ? 'cursor-not-allowed opacity-40 hover:bg-white/5 hover:text-[var(--theme-text-muted)]' : ''}`}
        >
          <span aria-hidden="true" className="text-xs">{snoozeIcon}</span>
          {snoozeLabel}
        </button>
      </Tooltip>
      {snoozeDisabled && (
        <span id={snoozeDescriptionId} className="sr-only">
          Only the comic currently waiting to be read can be snoozed.
        </span>
      )}
      <button
        type="button"
        aria-label="Delete"
        onClick={stopCardClick(onDelete)}
        className="inline-flex h-11 md:h-9 items-center justify-center rounded-lg px-3 text-sm font-medium text-[var(--theme-text-dim)] hover:bg-[var(--theme-danger)]/10 hover:text-[var(--theme-danger)] transition-colors"
      >
        Delete
      </button>
    </div>
  )
}
