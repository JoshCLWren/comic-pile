import Tooltip from '../../components/Tooltip'

interface QueueThreadActionsProps {
  readDisabled?: boolean
  readDisabledReason?: string
  onRead: () => void
}

export default function QueueThreadActions({
  readDisabled = false,
  readDisabledReason,
  onRead,
}: QueueThreadActionsProps) {
  const stopCardClick = (action: () => void) => (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    action()
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      role="group"
      aria-label="Primary action"
    >
      {readDisabled ? (
        <Tooltip content={readDisabledReason ?? 'Blocked by reading order'}>
          <button
            type="button"
            aria-label="Read"
            disabled
            title={readDisabledReason ?? 'Blocked by reading order'}
            onClick={(event: React.MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
            className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)]/25 px-4 text-sm font-bold text-white/60 hover:bg-[var(--theme-primary-action)]/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Read
          </button>
        </Tooltip>
      ) : (
        <button
          type="button"
          aria-label="Read"
          onClick={stopCardClick(onRead)}
          className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)] transition-colors"
        >
          Read
        </button>
      )}
    </div>
  )
}
