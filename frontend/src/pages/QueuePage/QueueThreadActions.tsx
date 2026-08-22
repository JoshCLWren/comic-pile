import Tooltip from '../../components/Tooltip'

interface QueueThreadActionsProps {
  title: string
  snoozeIcon: string
  snoozeLabel: string
  snoozeDisabled: boolean
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
      className="pl-8 md:pl-[2.75rem] flex flex-wrap gap-2"
      role="group"
      aria-label={`Actions for ${title}`}
    >
      <button type="button" aria-label="Read" onClick={stopCardClick(onRead)} className="px-3 py-2 rounded-lg bg-amber-600/20 text-amber-300 text-xs font-bold hover:bg-amber-600/30">📖 Read</button>
      <button type="button" aria-label="Edit" onClick={stopCardClick(onEdit)} className="px-3 py-2 rounded-lg bg-white/5 text-stone-300 text-xs font-bold hover:bg-white/10">✏️ Edit</button>
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
          className={`px-3 py-2 rounded-lg bg-teal-600/15 text-teal-300 text-xs font-bold hover:bg-teal-600/25 ${snoozeDisabled ? 'opacity-40 cursor-not-allowed hover:bg-teal-600/15' : ''}`}
        >
          {snoozeIcon} {snoozeLabel}
        </button>
      </Tooltip>
      {snoozeDisabled && (
        <span id={snoozeDescriptionId} className="sr-only">
          Only the comic currently waiting to be read can be snoozed.
        </span>
      )}
      <button type="button" aria-label="Delete" onClick={stopCardClick(onDelete)} className="px-3 py-2 rounded-lg bg-red-600/15 text-red-300 text-xs font-bold hover:bg-red-600/25">🗑 Delete</button>
    </div>
  )
}
