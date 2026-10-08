import { useState } from 'react'
import Modal from '../../components/Modal'
import type { ThreadListItem } from '../../types'

interface BulkMapComicVineDialogProps {
  isOpen: boolean
  threads: ThreadListItem[]
  onMapSelected: () => void
  onClose: () => void
}

export default function BulkMapComicVineDialog({
  isOpen,
  threads,
  onMapSelected,
  onClose,
}: BulkMapComicVineDialogProps) {
  const [isMapping, setIsMapping] = useState(false)

  const handleMapSelected = async () => {
    setIsMapping(true)
    try {
      await onMapSelected()
    } finally {
      setIsMapping(false)
    }
  }

  const threadCount = threads.length
  const totalIssues = threads.reduce((sum, thread) => sum + (thread.issues_remaining || 0), 0)

  return (
    <Modal
      isOpen={isOpen}
      title="Map Series to ComicVine"
      onClose={onClose}
      size="medium"
    >
      <div className="space-y-4">
        <p className="text-sm text-stone-400">
          You have {threadCount} unmapped series with {totalIssues} total issues. 
          This will open each series in the roll interface where you can map them to ComicVine.
        </p>

        {threadCount > 0 && (
          <div className="space-y-2 max-h-60 overflow-y-auto">
            <p className="text-xs font-bold uppercase tracking-widest text-stone-500 mb-2">
              Series to map:
            </p>
            {threads.map((thread) => (
              <div key={thread.id} className="flex items-center gap-2 text-sm">
                <span className="w-2 h-2 rounded-full bg-[var(--theme-comic-accent)]" />
                <span className="text-stone-300">{thread.title}</span>
                <span className="text-stone-500">({thread.format})</span>
                {thread.issues_remaining !== null && (
                  <span className="text-stone-400">
                    {thread.issues_remaining} issue{thread.issues_remaining === 1 ? '' : 's'}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isMapping}
            className="flex-1 py-3 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleMapSelected}
            disabled={isMapping || threadCount === 0}
            className="flex-1 py-3 rounded-xl bg-[var(--theme-comic-accent)] font-black text-stone-950 hover:bg-[var(--theme-comic-accent)]/80 transition-colors disabled:opacity-60"
          >
            {isMapping ? 'Mapping...' : `Map ${threadCount} Series`}
          </button>
        </div>
      </div>
    </Modal>
  )
}