import { useEffect, useState } from 'react'
import Modal from './Modal'
import GlossaryLink from './GlossaryLink'
import {
  readingOrdersApi,
  type ReadingOrderProjectionPreview,
  type ReadingOrderProjectionResult,
  type ReadingOrderSummary,
} from '../services/api-reading-orders'
import { getApiErrorDetail } from '../utils/apiError'

interface PlanProjectionDialogProps {
  isOpen: boolean
  planId: number
  planName: string
  onClose: () => void
}

const SOURCE_LABEL: Record<string, string> = {
  existing: 'Kept',
  added: 'Added',
  updated: 'Moved',
}

export default function PlanProjectionDialog({
  isOpen,
  planId,
  planName,
  onClose,
}: PlanProjectionDialogProps) {
  const [readingOrders, setReadingOrders] = useState<ReadingOrderSummary[]>([])
  const [selectedOrderId, setSelectedOrderId] = useState('')
  const [isLoadingOrders, setIsLoadingOrders] = useState(false)
  const [preview, setPreview] = useState<ReadingOrderProjectionPreview | null>(null)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [result, setResult] = useState<ReadingOrderProjectionResult | null>(null)
  const [isConfirming, setIsConfirming] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    let active = true
    setReadingOrders([])
    setSelectedOrderId('')
    setPreview(null)
    setResult(null)
    setError(null)
    setIsLoadingOrders(true)
    void readingOrdersApi.list()
      .then((response) => {
        if (active) setReadingOrders(response.reading_orders)
      })
      .catch((loadError: unknown) => {
        if (active) setError(getApiErrorDetail(loadError))
      })
      .finally(() => {
        if (active) setIsLoadingOrders(false)
      })
    return () => { active = false }
  }, [isOpen])

  const selectedOrder = readingOrders.find((order) => order.id === Number(selectedOrderId)) ?? null

  const runPreview = async () => {
    if (!selectedOrder) return
    setIsPreviewing(true)
    setError(null)
    setResult(null)
    try {
      const nextPreview = await readingOrdersApi.previewProjection(planId, selectedOrder.id)
      setPreview(nextPreview)
    } catch (previewError: unknown) {
      setError(getApiErrorDetail(previewError))
      setPreview(null)
    } finally {
      setIsPreviewing(false)
    }
  }

  const confirmProjection = async () => {
    if (!selectedOrder) return
    setIsConfirming(true)
    setError(null)
    try {
      const nextResult = await readingOrdersApi.confirmProjection(planId, selectedOrder.id)
      setResult(nextResult)
      setPreview(null)
    } catch (confirmError: unknown) {
      setError(getApiErrorDetail(confirmError))
    } finally {
      setIsConfirming(false)
    }
  }

  const hasConflicts = preview !== null && preview.conflicts.length > 0

  return (
    <Modal
      isOpen={isOpen}
      title="Project to reading order"
      onClose={onClose}
      data-testid="plan-projection-dialog"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      <p className="text-sm text-stone-400">
        Preview how “{planName}” would appear inside a saved{' '}
        <GlossaryLink id="reading-order">reading order</GlossaryLink>, then confirm to apply it.
        Your plan is never modified (<GlossaryLink id="projection">Projection</GlossaryLink>).
      </p>

      <label className="mt-4 block">
        <span className="text-xs font-bold uppercase tracking-wider text-stone-400">Reading order</span>
        <select
          value={selectedOrderId}
          onChange={(event) => {
            setSelectedOrderId(event.target.value)
            setPreview(null)
            setResult(null)
            setError(null)
          }}
          disabled={isLoadingOrders || isConfirming}
          className="mt-1 min-h-11 w-full rounded-xl border border-stone-700 bg-stone-900 px-3 text-stone-100 disabled:opacity-50"
          data-testid="projection-reading-order-select"
        >
          <option value="">{isLoadingOrders ? 'Loading reading orders…' : 'Select a reading order'}</option>
          {readingOrders.map((order) => (
            <option key={order.id} value={order.id}>{order.name} ({order.total_items} items)</option>
          ))}
        </select>
      </label>

      <div className="mt-4 flex gap-2">
        <button type="button" onClick={runPreview} disabled={!selectedOrder || isPreviewing || isConfirming} className="min-h-11 flex-1 rounded-xl bg-stone-800 px-4 font-bold text-stone-100 disabled:opacity-40">
          {isPreviewing ? 'Previewing…' : 'Preview projection'}
        </button>
        <button type="button" onClick={confirmProjection} disabled={!selectedOrder || isConfirming || hasConflicts} className="min-h-11 flex-1 rounded-xl bg-amber-500 px-4 font-black text-stone-950 disabled:opacity-40">
          {isConfirming ? 'Projecting…' : 'Confirm projection'}
        </button>
      </div>

      {error && <p role="alert" className="mt-4 rounded-xl border border-red-800 bg-red-950/30 p-3 text-red-200">{error}</p>}

      {preview && (
        <section aria-label="Projection preview" className="mt-4 space-y-3">
          <div className="flex items-center justify-between rounded-xl border border-stone-800 bg-stone-900 p-3">
            <div>
              <p className="font-bold text-stone-100">{preview.reading_order_name}</p>
              <p className="text-xs text-stone-500">{preview.total_positions} positions</p>
            </div>
            {preview.dropped_node_ids.length > 0 && (
              <p className="text-right text-xs text-stone-500">{preview.dropped_node_ids.length} dropped</p>
            )}
          </div>
          {hasConflicts ? (
            <div role="alert" className="rounded-xl border border-amber-800 bg-amber-950/20 p-3">
              <p className="font-bold text-amber-300">Resolve conflicts before projecting</p>
              <ul className="mt-2 space-y-1 text-sm text-amber-100">
                {preview.conflicts.map((conflict) => (
                  <li key={conflict.node_id}>{conflict.message}</li>
                ))}
              </ul>
            </div>
          ) : (
            <ol className="grid gap-1.5">
              {preview.entries.map((entry) => (
                <li key={`${entry.source_node_id ?? entry.thread_id}-${entry.position}`} className="flex items-center gap-2 rounded-xl border border-stone-800 bg-stone-900 px-3 py-2 text-sm">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-stone-800 text-xs font-black text-amber-300">{entry.position}</span>
                  <span className="min-w-0 flex-1 truncate text-stone-100">{entry.thread_title ?? `Thread ${entry.thread_id}`}</span>
                  <span className="shrink-0 text-[10px] font-black uppercase tracking-wider text-stone-500">{SOURCE_LABEL[entry.source] ?? entry.source}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}

      {result && (
        <section aria-label="Projection result" className="mt-4 rounded-xl border border-emerald-800 bg-emerald-950/20 p-3">
          <p className="font-bold text-emerald-300">Projection applied</p>
          <p className="mt-1 text-sm text-emerald-100">
            {result.added_count} added, {result.updated_count} moved, {result.kept_count} kept · {result.total_positions} total positions.
          </p>
        </section>
      )}
    </Modal>
  )
}
