import Tooltip from '../../components/Tooltip'
import type { ComicVineMappingHealth } from '../../types/comic-vine'
import { needsMappingAttention } from '../../hooks/useComicVineMapping'

interface QueueThreadActionsProps {
  title: string
  readDisabled?: boolean
  readDisabledReason?: string
  onRead: () => void
  mapping?: ComicVineMappingHealth | null
  onMapSeries?: () => void
}

export default function QueueThreadActions({
  title,
  readDisabled = false,
  readDisabledReason,
  onRead,
  mapping,
  onMapSeries,
}: QueueThreadActionsProps) {
  const stopCardClick = (action: () => void) => (event: React.MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    action()
  }

  const showMapSeries = mapping != null && needsMappingAttention(mapping)

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
      {showMapSeries && onMapSeries && (
        <Tooltip content="Map this series to ComicVine">
          <button
            type="button"
            aria-label={`Map ${title} to ComicVine`}
            onClick={stopCardClick(onMapSeries)}
            className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-amber-500 px-4 text-sm font-bold text-stone-950 hover:bg-amber-400 transition-colors"
          >
            Map series
          </button>
        </Tooltip>
      )}
    </div>
  )
}
