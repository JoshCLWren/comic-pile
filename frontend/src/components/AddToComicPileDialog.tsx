import { useState, useCallback, useEffect } from 'react'
import Modal from './Modal'
import { readingOrdersApi, type ReadingOrderSummary } from '../services/api-reading-orders'
import { useCreateThread } from '../hooks/useThread'
import { useToast } from '../contexts/useToast'

interface AddToComicPileDialogProps {
  isOpen: boolean
  seriesName: string | null
  issueNumber: string | null
  comicvineIssueId: string
  imageUrl: string | null
  onClose: () => void
  onAdded: (threadId: number) => void
}

export default function AddToComicPileDialog({
  isOpen,
  seriesName,
  issueNumber,
  comicvineIssueId,
  imageUrl,
  onClose,
  onAdded,
}: AddToComicPileDialogProps) {
  const { mutate: createThread, isPending } = useCreateThread()
  const { showToast } = useToast()

  const [title, setTitle] = useState('')
  const [readingOrders, setReadingOrders] = useState<ReadingOrderSummary[]>([])
  const [selectedOrderId, setSelectedOrderId] = useState<string>('')
  const [isLoadingOrders, setIsLoadingOrders] = useState(false)
  const [error, setError] = useState<string | null>(null)

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

    setError(null)
    try {
      const thread = await createThread({
        title: title.trim(),
        format: 'Comics',
        issues_remaining: 1,
        total_issues: 1,
        notes: `Imported from ComicVine (ID: ${comicvineIssueId})`,
      })

      if (selectedOrderId) {
        try {
          const orderDetail = await readingOrdersApi.getForThread(thread.id)
          const targetOrder = orderDetail.reading_orders.find(
            (o) => o.id === Number(selectedOrderId),
          )
          const nextPos = targetOrder && targetOrder.items.length > 0
            ? Math.max(...targetOrder.items.map((item) => item.position)) + 1
            : 1
          await readingOrdersApi.insertItem(Number(selectedOrderId), {
            thread_id: thread.id,
            position: nextPos,
          })
        } catch {
          showToast('Thread created but failed to add to reading order', 'warning')
        }
      }

      showToast(`Added "${title.trim()}" to ComicPile`, 'success')
      onAdded(thread.id)
      onClose()
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : 'Failed to create thread'
      setError(detail)
    }
  }, [title, comicvineIssueId, selectedOrderId, createThread, onAdded, onClose, showToast])

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
          disabled={isPending || !title.trim()}
          className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
        >
          {isPending ? 'Adding...' : 'Add to ComicPile'}
        </button>
      </div>
    </Modal>
  )
}
