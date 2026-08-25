import { useState, useCallback, useEffect } from 'react'
import Modal from './Modal'
import { comicVineApi } from '../services/api'
import { readingOrdersApi, type ReadingOrderSummary } from '../services/api-reading-orders'
import { useToast } from '../contexts/useToast'

interface AddToComicPileDialogProps {
  isOpen: boolean
  seriesName: string | null
  issueNumber: string | null
  comicvineIssueId: string
  imageUrl: string | null
  anchorBeforeThreadId?: number | null
  anchorAfterThreadId?: number | null
  onClose: () => void
  onAdded: (threadId: number) => void
}

export default function AddToComicPileDialog({
  isOpen,
  seriesName,
  issueNumber,
  comicvineIssueId,
  imageUrl,
  anchorBeforeThreadId = null,
  anchorAfterThreadId = null,
  onClose,
  onAdded,
}: AddToComicPileDialogProps) {
  const { showToast } = useToast()

  const [title, setTitle] = useState('')
  const [readingOrders, setReadingOrders] = useState<ReadingOrderSummary[]>([])
  const [selectedOrderId, setSelectedOrderId] = useState<string>('')
  const [isLoadingOrders, setIsLoadingOrders] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  useEffect(() => {
    if (isOpen) {
      const computedTitle = [seriesName, issueNumber ? `#${issueNumber}` : '']
        .filter(Boolean)
        .join(' ')
        .trim()
      setTitle(computedTitle || '')
      setSelectedOrderId('')
      setError(null)

      setIsLoadingOrders(true)
      readingOrdersApi.list().then((response) => {
        setReadingOrders(response.reading_orders)
      }).catch(() => {
        setReadingOrders([])
      }).finally(() => {
        setIsLoadingOrders(false)
      })
    }
  }, [isOpen, seriesName, issueNumber])

  const handleSubmit = useCallback(async () => {
    if (!title.trim()) {
      setError('Title is required')
      return
    }
    const parsedComicvineIssueId = Number.parseInt(comicvineIssueId, 10)
    if (!Number.isFinite(parsedComicvineIssueId)) {
      setError('This issue has no usable ComicVine identity to preserve')
      return
    }

    setError(null)
    setIsSubmitting(true)
    try {
      const result = await comicVineApi.importIssue({
        title: title.trim(),
        comicvine_issue_id: parsedComicvineIssueId,
        issue_number: issueNumber,
        reading_order_id: selectedOrderId ? Number(selectedOrderId) : null,
        anchor_before_thread_id: anchorBeforeThreadId,
        anchor_after_thread_id: anchorAfterThreadId,
      })

      showToast(`Added "${title.trim()}" to ComicPile`, 'success')
      onAdded(result.thread_id)
      onClose()
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : 'Failed to add to ComicPile'
      setError(detail)
    } finally {
      setIsSubmitting(false)
    }
  }, [title, comicvineIssueId, issueNumber, selectedOrderId, anchorBeforeThreadId, anchorAfterThreadId, onAdded, onClose, showToast])

  return (
    <Modal
      isOpen={isOpen}
      title="Add to ComicPile"
      onClose={onClose}
      data-testid="add-to-comicpile-dialog"
    >
      <div className="space-y-4">
        {error && (
          <div className="p-3 rounded-lg bg-rose-900/30 border border-rose-700/40 text-sm text-rose-300" role="alert">
            {error}
          </div>
        )}

        <div className="flex items-start gap-3 p-3 rounded-xl bg-stone-800/50 border border-stone-700/50">
          {imageUrl && (
            <img
              src={imageUrl}
              alt=""
              className="w-12 h-16 object-cover rounded-lg shrink-0"
            />
          )}
          <div className="min-w-0">
            <p className="text-[10px] font-black uppercase tracking-wider text-stone-500">
              ComicVine Issue
            </p>
            <p className="text-sm font-bold text-stone-200 truncate">
              {seriesName ?? 'Unknown Series'}{issueNumber ? ` #${issueNumber}` : ''}
            </p>
            <p className="text-[10px] text-stone-500">ID: {comicvineIssueId}</p>
          </div>
        </div>

        {(anchorBeforeThreadId != null || anchorAfterThreadId != null) && (
          <p
            className="text-[10px] text-stone-400"
            data-testid="placement-anchor-hint"
          >
            Will be placed between its story-arc neighbors in the selected order.
          </p>
        )}

        <div>
          <label htmlFor="add-thread-title" className="block text-[10px] font-black uppercase tracking-wider text-stone-500 mb-1.5">
            Thread Title
          </label>
          <input
            id="add-thread-title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Batman #125"
            className="w-full min-h-11 rounded-xl px-4 text-sm text-stone-100 bg-stone-800 border border-stone-600 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition"
          />
        </div>

        <div>
          <label htmlFor="reading-order-select" className="block text-[10px] font-black uppercase tracking-wider text-stone-500 mb-1.5">
            Add to Reading Order (optional)
          </label>
          <select
            id="reading-order-select"
            value={selectedOrderId}
            onChange={(e) => setSelectedOrderId(e.target.value)}
            className="w-full min-h-11 rounded-xl px-4 text-sm text-stone-100 bg-stone-800 border border-stone-600 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none transition"
          >
            <option value="">{isLoadingOrders ? 'Loading reading orders...' : 'None'}</option>
            {readingOrders.map((order) => (
              <option key={order.id} value={order.id}>
                {order.name} ({order.total_items} items)
              </option>
            ))}
          </select>
        </div>

        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || !title.trim()}
          className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
        >
          {isSubmitting ? 'Adding...' : 'Add to ComicPile'}
        </button>
      </div>
    </Modal>
  )
}
