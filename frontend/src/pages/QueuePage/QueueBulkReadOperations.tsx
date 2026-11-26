import { useBulkReadOperations } from '../../hooks/useBulkReadOperations'
import { issuesApi } from '../../services/api-issues'

/**
 * Durable, cross-tab review/undo surface for bulk read operations on Queue.
 * Kept out of the route composition so QueuePage stays a thin composition and
 * a completed series that leaves active search still has an Undo entry point.
 */
export default function QueueBulkReadOperations() {
  const {
    operations: bulkReadOperations,
    message: bulkUndoMessage,
    undo: undoBulkRead,
  } = useBulkReadOperations(issuesApi)

  if (bulkReadOperations.length === 0 && !bulkUndoMessage) return null

  return (
    <section
      className="surface-panel rounded-lg border border-[var(--theme-border)] p-3 space-y-2"
      data-testid="bulk-read-operations"
      aria-label="Reviewable bulk reads"
    >
      <h2 className="text-sm font-bold text-[var(--theme-text-primary)]">
        Reviewable bulk reads
      </h2>
      {bulkUndoMessage && (
        <p className="text-xs text-[var(--theme-text-muted)]" role="status">{bulkUndoMessage}</p>
      )}
      <ul className="divide-y divide-[var(--theme-border)]">
        {bulkReadOperations.map(({ threadId, operation }) => (
          <li key={operation.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
            <span className="text-xs text-[var(--theme-text-muted)]">
              Operation #{operation.id} · {operation.items.length} issue
              {operation.items.length === 1 ? '' : 's'} · series {threadId}
            </span>
            <button
              type="button"
              className="text-xs font-semibold text-[var(--theme-text-primary)] underline disabled:opacity-50"
              onClick={() => void undoBulkRead(threadId, operation.id)}
            >
              Undo
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
