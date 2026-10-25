interface Props {
  isError: boolean
  onRetry: () => void
}

/** One recoverable notice for the Queue's batched boundary request. */
export function QueueBoundaryNotice({ isError, onRetry }: Props) {
  if (!isError) return null
  return (
    <div role="alert" className="surface-panel rounded-xl p-3 text-sm text-[var(--theme-text-muted)] md:p-4">
      <p>Reading boundaries could not be loaded. Rows fall back to their recorded prerequisites.</p>
      <button type="button" onClick={() => void onRetry()} className="min-h-11 font-semibold text-[var(--theme-continuity-accent)] underline">
        Retry reading boundaries
      </button>
    </div>
  )
}
