interface QueueThreadActionsProps {
  title: string
  onRead: () => void
}

/**
 * Opening an exact owned-issue editor is not a Roll eligibility decision.
 * Prerequisites only control automatic offers, never this manual action.
 */
export default function QueueThreadActions({ title, onRead }: QueueThreadActionsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={`Actions for ${title}`}>
      <button
        type="button"
        aria-label="Read & Rate"
        onClick={(event) => {
          event.stopPropagation()
          onRead()
        }}
        className="inline-flex h-11 @2xl:h-9 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-4 text-sm font-bold text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)] transition-colors"
      >
        Read & Rate
      </button>
    </div>
  )
}
