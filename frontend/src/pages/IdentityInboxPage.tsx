import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { isObject, isNonEmptyString, isString } from '../utils/runtimeChecks'
import {
  useIdentityInbox,
  useConfirmInboxCandidate,
  useRejectInboxCandidate,
  useDeferInboxItem,
  useSkipInboxItem,
} from '../hooks/useIdentityInbox'
import type { IdentityInboxCandidate as InboxCandidate, IdentityInboxItem as InboxItem } from '../services/api'

type MetadataValue = string | Record<string, string> | null
type EvidenceValue = string | string[] | null

function statusColor(status: string): string {
  switch (status) {
    case 'unresolved':
      return 'text-[var(--theme-text-primary)] bg-[var(--theme-comic-accent)]/20'
    case 'candidate':
      return 'text-[var(--theme-primary-action)] bg-[var(--theme-primary-action)]/15'
    case 'deferred':
      return 'text-[var(--theme-text-muted)] bg-[var(--theme-bg-panel)]'
    default:
      return 'text-[var(--theme-text-dim)] bg-[var(--theme-bg-panel)]'
  }
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence === null) return <span className="text-xs text-[var(--theme-text-dim)]">N/A</span>
  const pct = Math.round(confidence * 100)
  const color = pct >= 70
    ? 'bg-[var(--theme-primary-action)]'
    : pct >= 40
      ? 'bg-[var(--theme-comic-accent)]'
      : 'bg-[var(--theme-danger)]'
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-[var(--theme-border)] rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-[var(--theme-text-dim)]">{pct}%</span>
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
    isNonEmptyString(value) ? value : null

  const volumeObj = meta.volume
  const volumeName =
    isObject(volumeObj)
      ? toText(volumeObj.name)
      : toText(meta.volume_name)
  const issueName = toText(meta.name) ?? toText(meta.issue_name)
  const evidenceItems = Array.isArray(candidate.evidence_json.evidence)
    ? candidate.evidence_json.evidence.filter(isString)
    : []

  return (
    <div className="border border-[var(--theme-border)] rounded-lg p-3 bg-[var(--theme-bg-panel)] hover:border-[var(--theme-text-dim)] transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-[var(--theme-text-primary)] truncate">
            {candidate.comicvine_id ? `#${candidate.comicvine_id}` : 'Unknown'}
            {volumeName && (
              <span className="text-[var(--theme-text-muted)] font-normal ml-1">({volumeName})</span>
            )}
          </div>
          {issueName && (
            <div className="text-xs text-[var(--theme-text-muted)] mt-0.5">{issueName}</div>
          )}
          <div className="flex items-center gap-3 mt-1.5">
            <ConfidenceBar confidence={candidate.confidence} />
            {candidate.evidence_source && (
              <span className="text-xs text-[var(--theme-text-dim)]">{candidate.evidence_source}</span>
            )}
          </div>
          {candidate.evidence_json &&
            Array.isArray(candidate.evidence_json.evidence) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {evidenceItems.map((e, i) => (
                  <span
                    key={i}
                    className="inline-block text-xs bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] px-2 py-0.5 rounded border border-[var(--theme-border)]"
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
              className="text-xs text-[var(--theme-text-primary)] hover:underline mt-1 inline-block"
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
            className="px-2.5 py-1 text-xs font-semibold rounded-md bg-[var(--theme-primary-action)] text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
            className="px-2.5 py-1 text-xs font-semibold rounded-md bg-[var(--theme-danger)]/15 text-[var(--theme-danger)] hover:bg-[var(--theme-danger)]/25 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
  isMutating,
}: {
  item: InboxItem
  onConfirm: (mappingId: number, identityId: number) => void
  onReject: (mappingId: number, identityId: number, reason: string) => Promise<void>
  onDefer: (mappingId: number) => void
  onSkip: (mappingId: number) => void
  expandedId: number | null
  toggleExpand: (id: number) => void
  isMutating: boolean
}) {
  const isExpanded = expandedId === item.mapping_id
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectForm, setShowRejectForm] = useState(false)

  const handleReject = async (identityId: number) => {
    if (!rejectReason.trim()) {
      setShowRejectForm(true)
      return
    }
    const reason = rejectReason
    setShowRejectForm(false)
    try {
      await onReject(item.mapping_id, identityId, reason)
      setRejectReason('')
    } catch {
      setRejectReason(reason)
      setShowRejectForm(true)
    }
  }

  return (
    <div className="border border-[var(--theme-border)] rounded-xl bg-[var(--theme-bg-panel)] shadow-sm overflow-hidden">
      <div className="w-full px-4 py-3 hover:bg-white/[0.04] transition-colors flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={() => toggleExpand(item.mapping_id)}
          aria-expanded={isExpanded}
          className="flex-1 min-w-0 text-left cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[var(--theme-focus-ring)] rounded"
        >
          <span className="flex items-center gap-2">
            <span className="font-semibold text-sm text-[var(--theme-text-primary)] hover:text-[var(--theme-text-primary)] hover:underline truncate">
              {item.thread_title}
            </span>
            <span className="text-xs text-[var(--theme-text-dim)]">#{item.issue_number}</span>
          </span>
          <span className="block text-xs text-[var(--theme-text-muted)] mt-0.5">{item.why_stopped}</span>
        </button>
        <div className="flex items-center gap-2 shrink-0">
          <Link
            to={`/thread/${item.thread_id}`}
            className="text-xs text-[var(--theme-text-primary)] hover:underline shrink-0"
            aria-label={`Open thread ${item.thread_id}`}
          >
            Open
          </Link>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${statusColor(item.status)}`}>
            {item.status}
          </span>
          <span className="text-[var(--theme-text-dim)] text-xs">{isExpanded ? '\u25B2' : '\u25BC'}</span>
        </div>
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 border-t border-[var(--theme-border)]">
          <div className="mt-3 space-y-2">
            <div className="text-xs font-semibold text-[var(--theme-text-muted)] uppercase tracking-wider">Candidates</div>
            {item.candidates.length === 0 ? (
              <div className="text-xs text-[var(--theme-text-dim)] italic">No candidates found for this issue.</div>
            ) : (
              item.candidates.map((c) => (
                <CandidateCard
                  key={c.external_identity_id}
                  candidate={c}
                  onConfirm={(id) => onConfirm(item.mapping_id, id)}
                  onReject={(id) => handleReject(id)}
                  isConfirming={isMutating}
                  isRejecting={isMutating}
                />
              ))
            )}

            {showRejectForm && (
              <div className="mt-2 p-2 bg-[var(--theme-danger)]/10 rounded-lg border border-[var(--theme-danger)]/30">
                <label className="block text-xs font-medium text-[var(--theme-danger)] mb-1">Rejection reason</label>
                <input
                  type="text"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Why is this candidate wrong?"
                  className="w-full px-2 py-1 text-xs border border-[var(--theme-danger)]/40 rounded bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--theme-danger)]"
                />
                <div className="flex gap-2 mt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setShowRejectForm(false)
                      setRejectReason('')
                    }}
                    className="px-2 py-1 text-xs text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--theme-border)]">
              <button
                type="button"
                onClick={() => onDefer(item.mapping_id)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
              >
                Defer
              </button>
              <button
                type="button"
                onClick={() => onSkip(item.mapping_id)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
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

const INBOX_LIMIT = 20

export default function IdentityInboxPage() {
  const [offset, setOffset] = useState(0)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const { data, isPending, isError, error } = useIdentityInbox(offset)
  const confirmMutation = useConfirmInboxCandidate()
  const rejectMutation = useRejectInboxCandidate()
  const deferMutation = useDeferInboxItem()
  const skipMutation = useSkipInboxItem()

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const isMutating = confirmMutation.isPending || rejectMutation.isPending || deferMutation.isPending || skipMutation.isPending

  const toggleExpand = useCallback((id: number) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }, [])

  const handleConfirm = useCallback(
    (mappingId: number, identityId: number) => {
      confirmMutation.mutate({ mappingId, payload: { external_identity_id: identityId } })
    },
    [confirmMutation],
  )

  const handleReject = useCallback(
    async (mappingId: number, identityId: number, reason: string): Promise<void> => {
      await rejectMutation.mutateAsync({
        mappingId,
        payload: { external_identity_id: identityId, rejection_reason: reason },
      })
    },
    [rejectMutation],
  )

  const handleDefer = useCallback(
    (mappingId: number) => {
      deferMutation.mutate(mappingId)
    },
    [deferMutation],
  )

  const handleSkip = useCallback(
    (mappingId: number) => {
      skipMutation.mutate(mappingId)
    },
    [skipMutation],
  )

  const totalPages = Math.ceil(total / INBOX_LIMIT)
  const currentPage = Math.floor(offset / INBOX_LIMIT) + 1

  const errorMessage = isError
    ? error instanceof Error
      ? error.message
      : 'Failed to load inbox'
    : null

  const actionError =
    confirmMutation.error ?? rejectMutation.error ?? deferMutation.error ?? skipMutation.error
  const actionErrorMessage = actionError
    ? actionError instanceof Error
      ? actionError.message
      : 'Action failed'
    : null

  return (
    <section aria-label="Identity reconciliation inbox" className="pt-4 pb-12 w-full">
      <h1 className="text-2xl font-bold mb-2 text-[var(--theme-text-primary)]">Identity Inbox</h1>
      <p className="text-sm text-[var(--theme-text-muted)] mb-6">
        Resolve unmatched or ambiguous external comic identities. Confirm the correct match,
        reject wrong candidates, or defer for later.
      </p>

      {actionErrorMessage && (
        <div className="p-3 mb-4 bg-[var(--theme-danger)]/10 border border-[var(--theme-danger)]/30 rounded-lg text-sm text-[var(--theme-danger)]">
          {actionErrorMessage}
        </div>
      )}

      {errorMessage && (
        <div className="p-3 mb-4 bg-[var(--theme-danger)]/10 border border-[var(--theme-danger)]/30 rounded-lg text-sm text-[var(--theme-danger)]">
          {errorMessage}
        </div>
      )}

      {isPending ? (
        <div className="text-center py-12 text-[var(--theme-text-dim)]">Loading...</div>
      ) : items.length === 0 ? (
        <div className="text-center py-12">
          <div className="text-4xl mb-3">{'\u2714\uFE0F'}</div>
          <div className="text-sm text-[var(--theme-text-muted)] font-medium">All clear!</div>
          <div className="text-xs text-[var(--theme-text-dim)] mt-1">No unresolved identities in your inbox.</div>
        </div>
      ) : (
        <>
          <div className="text-xs text-[var(--theme-text-dim)] mb-3">
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
                isMutating={isMutating}
              />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-4 mt-6">
              <button
                type="button"
                onClick={() => setOffset((o) => Math.max(0, o - INBOX_LIMIT))}
                disabled={offset === 0}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                Previous
              </button>
              <span className="text-xs text-[var(--theme-text-dim)]">
                Page {currentPage} of {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setOffset((o) => o + INBOX_LIMIT)}
                disabled={currentPage >= totalPages}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
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
