import Tooltip from '../../components/Tooltip'

interface QueueThreadActionsProps {
  title: string
  readDisabled?: boolean
  readDisabledReason?: string
  onRead: () => void
  onMapComicVine?: () => void
  isMapped?: boolean
}

export default function QueueThreadActions({
  title,
  readDisabled = false,
  readDisabledReason,
  onRead,
  onMapComicVine,
  isMapped = false,
}: QueueThreadActionsProps) {
  const stopCardClick = (action: () => void) => (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    action()
  }

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
            aria-label="Read & Rate"
            disabled
            title={readDisabledReason ?? 'Blocked by dependency'}
            onClick={(event: React.MouseEvent<HTMLButtonElement>) => event.stopPropagation()}
            className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)]/25 px-4 text-sm font-bold text-white/60 hover:bg-[var(--theme-primary-action)]/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Read & Rate
          </button>
        </Tooltip>
      ) : (
        <button
          type="button"
          aria-label="Read & Rate"
          onClick={stopCardClick(onRead)}
          className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-white hover:bg-[var(--theme-primary-action-hover)] transition-colors"
        >
          Read & Rate
        </button>
      )}
      
      {onMapComicVine && (
        <Tooltip content={isMapped ? 'Change ComicVine mapping' : 'Map to ComicVine'}>
          <button
            type="button"
            aria-label={isMapped ? 'Change ComicVine mapping' : 'Map to ComicVine'}
            onClick={stopCardClick(onMapComicVine)}
            className={`inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg px-4 text-sm font-bold transition-colors ${
              isMapped 
                ? 'bg-[var(--theme-comic-accent)]/20 border border-[var(--theme-comic-accent)] text-[var(--theme-comic-accent)] hover:bg-[var(--theme-comic-accent)]/30' 
                : 'bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:bg-white/10 hover:text-[var(--theme-text-primary)]'
            }`}
          >
            {isMapped ? '🔗 Linked' : '🔗 Map'}
          </button>
        </Tooltip>
      )}
    </div>
  )
}
