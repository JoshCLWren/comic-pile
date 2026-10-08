import { useQuery } from '@tanstack/react-query'
import Modal from '../../components/Modal'
import ComicVineSearchDialog from '../../components/ComicVineSearchDialog'
import { issuesApi } from '../../services/api-issues'
import { threadsApi } from '../../services/api-threads'
import { queryKeys } from '../../query/queryKeys'

/** Issue that anchors the Map series repair scope for a queue thread. */
export interface MapSeriesAnchor {
  issueId: number
  issueNumber: string | null
}

/**
 * Resolve the anchor issue for a Map series repair.
 *
 * The series-mapping preview contract (#2721) anchors scope on an origin
 * issue, never on a thread id, so the queue entry point must resolve one
 * real issue before launching the shared correction flow. Prefer the next
 * unread issue and fall back to the first tracked issue. Returns null when
 * the thread tracks no issues at all.
 *
 * Runs only when the caller opens the flow; queue cards never fetch issues
 * to render their mapping-health indicator.
 *
 * Args:
 *     threadId: The queue thread being repaired.
 *
 * Returns:
 *     The anchor issue, or null when the thread has no tracked issues.
 */
async function resolveMapSeriesAnchor(threadId: number): Promise<MapSeriesAnchor | null> {
  const detail = await threadsApi.get(threadId)
  if (detail.next_unread_issue_id != null) {
    return {
      issueId: detail.next_unread_issue_id,
      issueNumber: detail.next_unread_issue_number ?? null,
    }
  }
  const firstPage = await issuesApi.list(threadId, { page_size: 1 })
  const first = firstPage.issues[0] ?? null
  if (first === null) {
    return null
  }
  return { issueId: first.id, issueNumber: first.issue_number }
}

/**
 * Load the Map series anchor issue for a queue thread.
 *
 * @param threadId - The queue thread being repaired, or null when none is selected.
 * @param enabled - Whether the anchor should load (true only while the dialog is open).
 * @returns The TanStack Query result carrying the anchor, null, or an error.
 */
export function useMapSeriesAnchor(threadId: number | null, enabled: boolean) {
  return useQuery({
    queryKey:
      threadId != null ? [...queryKeys.thread.detail(threadId), 'map-series-anchor'] : [],
    queryFn: () => resolveMapSeriesAnchor(threadId!),
    enabled: enabled && threadId != null,
    retry: false,
  })
}

interface MapSeriesDialogProps {
  isOpen: boolean
  threadId: number | null
  threadTitle: string
  onClose: () => void
  /** Called after a mapping commit lands so the caller can refresh queue health. */
  onMapped: () => void
}

/**
 * Queue entry point for repairing a series' ComicVine identity.
 *
 * Resolves one real anchor issue for the thread and hands it to the shared
 * issue-correction dialog, whose sibling step runs the #2721 preview and
 * #2722 commit flow for the remaining issues. Canceling or failing before a
 * confirm changes nothing; a successful commit notifies the caller so queue
 * mapping health refreshes without a hard reload.
 *
 * @param isOpen - Whether the dialog is visible.
 * @param threadId - The queue thread being repaired.
 * @param threadTitle - The queue thread title used as the series search seed.
 * @param onClose - Closes the dialog without changing anything.
 * @param onMapped - Refreshes queue mapping health after a commit.
 * @returns The Map series dialog, or null when closed.
 */
export default function MapSeriesDialog({
  isOpen,
  threadId,
  threadTitle,
  onClose,
  onMapped,
}: MapSeriesDialogProps) {
  const anchor = useMapSeriesAnchor(threadId, isOpen)

  if (!isOpen) {
    return null
  }

  if (threadId == null) {
    return (
      <Modal isOpen title="Map series" onClose={onClose}>
        <div className="space-y-4" data-testid="map-series-error">
          <p role="alert" className="text-sm text-stone-300">
            Couldn&apos;t load the issues for {threadTitle}. No mappings were changed.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
          >
            Close
          </button>
        </div>
      </Modal>
    )
  }

  if (anchor.isError) {
    return (
      <Modal isOpen title="Map series" onClose={onClose}>
        <div className="space-y-4" data-testid="map-series-error">
          <p role="alert" className="text-sm text-stone-300">
            Couldn&apos;t load the issues for {threadTitle}. No mappings were changed.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={() => void anchor.refetch()}
              className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
            >
              Try again
            </button>
            <button
              type="button"
              onClick={onClose}
              className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
            >
              Close
            </button>
          </div>
        </div>
      </Modal>
    )
  }

  if (anchor.isPending) {
    return (
      <Modal isOpen title="Map series" onClose={onClose}>
        <div className="flex justify-center py-8" data-testid="map-series-loading">
          <div
            className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin"
            role="status"
            aria-label={`Loading issues for ${threadTitle}`}
          />
        </div>
      </Modal>
    )
  }

  if (anchor.data == null) {
    return (
      <Modal isOpen title="Map series" onClose={onClose}>
        <div className="space-y-4" data-testid="map-series-empty">
          <p className="text-sm text-stone-300">
            {threadTitle} has no tracked issues to map yet.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
          >
            Close
          </button>
        </div>
      </Modal>
    )
  }

  return (
    <ComicVineSearchDialog
      isOpen
      issueId={anchor.data.issueId}
      threadTitle={threadTitle}
      issueNumber={anchor.data.issueNumber}
      onClose={onClose}
      onConfirmed={() => {
        onClose()
        onMapped()
      }}
    />
  )
}
