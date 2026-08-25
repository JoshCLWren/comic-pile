import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'

interface InboxCandidate {
  external_identity_id: number
  provider: string
  comicvine_id: string | null
  external_url: string | null
  metadata_json: Record<string, unknown>
  status: string
  confidence: number | null
  evidence_source: string | null
  evidence_json: Record<string, unknown>
  rejection_reason: string | null
}

interface InboxItem {
  mapping_id: number
  issue_id: number
  thread_id: number
  thread_title: string
  issue_number: string
  status: string
  provider: string | null
  source_entry_summary: string
  why_stopped: string
  candidates: InboxCandidate[]
  created_at: number | null
  updated_at: number | null
}

interface InboxResponse {
  items: InboxItem[]
  total: number
  offset: number
  limit: number
}

function statusColor(status: string): string {
  switch (status) {
    case 'unresolved':
      return 'text-amber-600 bg-amber-100'
    case 'candidate':
      return 'text-blue-600 bg-blue-100'
    case 'deferred':
      return 'text-stone-600 bg-stone-100'
    default:
      return 'text-stone-500 bg-stone-50'
  }
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence === null) return <span className="text-xs text-stone-400">N/A</span>
  const pct = Math.round(confidence * 100)
  const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-stone-200 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-stone-500">{pct}%</span>
    </div>
  )
}

function CandidateCard({
  candidate,
  onConfirm,
  onReject,
  isConfirming,
  isRejecting,
}: {
  candidate: InboxCandidate
  onConfirm: (id: number) => void
  onReject: (id: number) => void
  isConfirming: boolean
  isRejecting: boolean
}) {
  const meta = candidate.metadata_json
  const toText = (value: unknown): string | null =>
    typeof value === 'string' && value.length > 0 ? value : null

  const volumeObj = meta.volume
  const volumeName =
    typeof volumeObj === 'object' && volumeObj !== null
      ? toText((volumeObj as Record<string, unknown>).name)
      : toText(meta.volume_name)
  const issueName = toText(meta.name) ?? toText(meta.issue_name)

  return (
    <div className="border border-stone-200 rounded-lg p-3 bg-white hover:border-stone-300 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-stone-800 truncate">
            {candidate.comicvine_id ? `#${candidate.comicvine_id}` : 'Unknown'}
            {volumeName && (
              <span className="text-stone-500 font-normal ml-1">({volumeName})</span>
            )}
          </div>
          {issueName && (
            <div className="text-xs text-stone-600 mt-0.5">{issueName}</div>
          )}
          <div className="flex items-center gap-3 mt-1.5">
            <ConfidenceBar confidence={candidate.confidence} />
            {candidate.evidence_source && (
              <span className="text-xs text-stone-400">{candidate.evidence_source}</span>
            )}
          </div>
          {candidate.evidence_json &&
            Array.isArray(candidate.evidence_json.evidence) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(candidate.evidence_json.evidence as string[]).map((e, i) => (
                  <span
                    key={i}
                    className="inline-block text-xs bg-stone-100 text-stone-600 px-2 py-0.5 rounded"
                  >
                    {e}
                  </span>
                ))}
              </div>
            )}
          {candidate.external_url && (
            <a
              href={candidate.external_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-blue-500 hover:underline mt-1 inline-block"
            >
              View on provider
            </a>
          )}
        </div>
        <div className="flex gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() => onConfirm(candidate.external_identity_id)}
            disabled={isConfirming || candidate.status === 'confirmed'}
            className="px-2.5 py-1 text-xs font-semibold rounded-md bg-green-600 text-white hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {candidate.status === 'confirmed'
              ? 'Confirmed'
              : isConfirming
                ? '...'
                : 'Confirm'}
          </button>
          <button
            type="button"
            onClick={() => onReject(candidate.external_identity_id)}
            disabled={isRejecting || candidate.status === 'rejected'}
            className="px-2.5 py-1 text-xs font-semibold rounded-md bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {isRejecting ? '...' : 'Reject'}
          </button>
        </div>
      </div>
    </div>
  )
}

function InboxItemCard({
  item,
  onConfirm,
  onReject,
  onDefer,
  onSkip,
  expandedId,
  toggleExpand,
}: {
  item: InboxItem
  onConfirm: (mappingId: number, identityId: number) => void
  onReject: (mappingId: number, identityId: number, reason: string) => void
  onDefer: (mappingId: number) => void
  onSkip: (mappingId: number) => void
  expandedId: number | null
  toggleExpand: (id: number) => void
}) {
  const isExpanded = expandedId === item.mapping_id
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  const handleReject = async (identityId: number) => {
    if (!rejectReason.trim()) {
      setShowRejectForm(true)
      return
    }
    setActionLoading(true)
    try {
      await onReject(item.mapping_id, identityId, rejectReason)
      setRejectReason('')
      setShowRejectForm(false)
    } finally {
      setActionLoading(false)
    }
  }

  return (
    <div className="border border-stone-200 rounded-xl bg-white shadow-sm overflow-hidden">
      <div className="w-full px-4 py-3 hover:bg-stone-50 transition-colors flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => toggleExpand(item.mapping_id)}
          aria-expanded={isExpanded}
          className="flex-1 min-w-0 text-left cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 rounded"
        >
          <span className="flex items-center gap-2">
            <span className="font-semibold text-sm text-stone-800 hover:text-blue-600 hover:underline truncate">
              {item.thread_title}
            </span>
            <span className="text-xs text-stone-400">#{item.issue_number}</span>
          </span>
          <span className="block text-xs text-stone-500 mt-0.5">{item.why_stopped}</span>
        </button>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            to={`/thread/${item.thread_id}`}
            className="text-xs text-blue-500 hover:underline shrink-0"
            aria-label={`Open thread ${item.thread_id}`}
          >
            Open
          </Link>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${statusColor(item.status)}`}>
            {item.status}
          </span>
          <span className="text-stone-400 text-xs">{isExpanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 border-t border-stone-100">
          <div className="mt-3 space-y-2">
            <div className="text-xs font-semibold text-stone-600 uppercase tracking-wider">Candidates</div>
            {item.candidates.length === 0 ? (
              <div className="text-xs text-stone-400 italic">No candidates found for this issue.</div>
            ) : (
              item.candidates.map((c) => (
                <CandidateCard
                  key={c.external_identity_id}
                  candidate={c}
                  onConfirm={(id) => onConfirm(item.mapping_id, id)}
                  onReject={(id) => handleReject(id)}
                  isConfirming={actionLoading}
                  isRejecting={actionLoading}
                />
              ))
            )}

            {showRejectForm && (
              <div className="mt-2 p-2 bg-red-50 rounded-lg border border-red-200">
                <label className="block text-xs font-medium text-red-700 mb-1">Rejection reason</label>
                <input
                  type="text"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Why is this candidate wrong?"
                  className="w-full px-2 py-1 text-xs border border-red-300 rounded bg-white focus:outline-none focus:ring-1 focus:ring-red-500"
                />
                <div className="flex gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setShowRejectForm(false)
                      setRejectReason('')
                    }}
                    className="px-2 py-1 text-xs text-stone-600 hover:text-stone-800"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="flex gap-2 mt-3 pt-3 border-t border-stone-100">
              <button
                type="button"
                onClick={() => onDefer(item.mapping_id)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-stone-100 text-stone-700 hover:bg-stone-200 transition-colors"
              >
                Defer
              </button>
              <button
                type="button"
                onClick={() => onSkip(item.mapping_id)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-stone-100 text-stone-700 hover:bg-stone-200 transition-colors"
              >
                Skip
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function IdentityInboxPage() {
  const [items, setItems] = useState<InboxItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [offset, setOffset] = useState(0)
  const limit = 20

  const fetchItems = useCallback(async (off: number) => {
    setLoading(true)
    setError(null)
    try {
      const response = await api.get<InboxResponse>('/v1/identity-inbox', {
        params: { offset: off, limit },
      })
      setItems(response.items)
      setTotal(response.total)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to load inbox'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => {
    void fetchItems(offset)
  }, [fetchItems, offset])

  const toggleExpand = useCallback((id: number) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }, [])

  const handleConfirm = useCallback(async (mappingId: number, identityId: number) => {
    try {
      await api.post(`/v1/identity-inbox/${mappingId}/confirm`, {
        external_identity_id: identityId,
      })
      void fetchItems(offset)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Confirm failed'
      setError(message)
    }
  }, [fetchItems, offset])

  const handleReject = useCallback(async (mappingId: number, identityId: number, reason: string) => {
    try {
      await api.post(`/v1/identity-inbox/${mappingId}/reject`, {
        external_identity_id: identityId,
        rejection_reason: reason,
      })
      void fetchItems(offset)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Reject failed'
      setError(message)
    }
  }, [fetchItems, offset])

  const handleDefer = useCallback(async (mappingId: number) => {
    try {
      await api.post(`/v1/identity-inbox/${mappingId}/defer`)
      void fetchItems(offset)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Defer failed'
      setError(message)
    }
  }, [fetchItems, offset])

  const handleSkip = useCallback(async (mappingId: number) => {
    try {
      await api.post(`/v1/identity-inbox/${mappingId}/skip`)
      void fetchItems(offset)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Skip failed'
      setError(message)
    }
  }, [fetchItems, offset])

  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <section aria-label="Identity reconciliation inbox" className="pt-4 pb-12 w-full">
      <h1 className="text-2xl font-bold mb-2">Identity Inbox</h1>
      <p className="text-sm text-stone-500 mb-6">
        Resolve unmatched or ambiguous external comic identities. Confirm the correct match,
        reject wrong candidates, or defer for later.
      </p>

      {error && (
        <div className="p-3 mb-4 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-stone-400">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl mb-3">{'\u2714\uFE0F'}</div>
          <div className="text-sm text-stone-500 font-medium">All clear!</div>
          <div className="text-xs text-stone-400 mt-1">No unresolved identities in your inbox.</div>
        </div>
      ) : (
        <>
          <div className="text-xs text-stone-400 mb-3">
            {total} unresolved {total === 1 ? 'item' : 'items'}
          </div>
          <div className="space-y-3">
            {items.map((item) => (
              <InboxItemCard
                key={item.mapping_id}
                item={item}
                onConfirm={handleConfirm}
                onReject={handleReject}
                onDefer={handleDefer}
                onSkip={handleSkip}
                expandedId={expandedId}
                toggleExpand={toggleExpand}
              />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-4 mt-6">
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
                disabled={offset === 0}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-stone-100 text-stone-700 hover:bg-stone-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <span className="text-xs text-stone-500">
                Page {currentPage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setOffset((o) => o + limit)}
                disabled={currentPage >= totalPages}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-stone-100 text-stone-700 hover:bg-stone-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  )
}
