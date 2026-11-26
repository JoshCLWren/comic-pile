import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { isObject, isNonEmptyString, isString } from '../utils/runtimeChecks'
import {
  useIdentityInbox,
  useIdentityInboxSearch,
  useConfirmInboxCandidate,
  useRejectInboxCandidate,
  useDeferInboxItem,
  useSkipInboxItem,
} from '../hooks/useIdentityInbox'
import type {
  IdentityInboxCandidate as InboxCandidate,
  IdentityInboxItem as InboxItem,
} from '../services/api-identity'
import { ComicIssueCover } from '../components/ComicIssueCard'

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
  // Candidate metadata is provider-owned, not a confirmed owned issue card.
  // Render its own ComicVine artwork, never a cover borrowed from the issue
  // being mapped or a candidate with a different identity.
  const image = isObject(meta.image) ? meta.image : null
  const coverUrl =
    toText(meta.image_url) ??
    toText(meta.primary_image) ??
    (image ? (
      toText(image.medium_url) ??
      toText(image.small_url) ??
      toText(image.original_url) ??
      toText(image.thumb_url)
    ) : null)
  const evidenceItems = Array.isArray(candidate.evidence_json.evidence)
    ? candidate.evidence_json.evidence.filter(isString)
    : []

  return (
    <div className="border border-[var(--theme-border)] rounded-lg p-3 bg-[var(--theme-bg-panel)] hover:border-[var(--theme-text-dim)] transition-colors">
      <div className="flex items-start justify-between gap-2">
        <ComicIssueCover
          coverImageUrl={coverUrl}
          threadTitle={volumeName ?? issueName ?? 'ComicVine candidate'}
          issueNumber={toText(meta.issue_number) ?? ''}
          variant="compact"
          imageClassName="h-full w-full object-cover"
        />
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

/** #5434: reviewer-driven discovery with explainable scores and a partial
 * series plan. Unambiguous candidates are confirmed through the existing
 * confirmation endpoint; ambiguous or missing issues stay in the inbox. */
function MatchSearchPanel({
  item,
  onConfirm,
}: {
  item: InboxItem
  onConfirm: (mappingId: number, identityId: number) => void
}) {
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const { data, isPending, isError } = useIdentityInboxSearch(
    query,
    item.issue_id,
    query.length > 0,
  )

  return (
    <div className="mt-3 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)] p-3">
      <div className="text-xs font-semibold text-[var(--theme-text-primary)]">
        Find a ComicVine match
      </div>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
        Search by a different name or paste a ComicVine volume or issue URL.
      </p>
      <form
        className="mt-2 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          setQuery(input.trim())
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Series name or ComicVine URL"
          aria-label="ComicVine search query"
          className="min-w-0 flex-1 px-2 py-1 text-xs border border-[var(--theme-border)] rounded bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--theme-focus-ring)]"
        />
        <button
          type="submit"
          className="px-3 py-1 text-xs font-medium rounded bg-[var(--theme-primary-action)] text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)]"
        >
          Search
        </button>
      </form>

      {isPending && <p className="mt-2 text-xs text-[var(--theme-text-muted)]">Searching…</p>}
      {isError && (
        <p className="mt-2 text-xs text-[var(--theme-error)]">
          Search is unavailable right now. You can defer or map this issue manually.
        </p>
      )}

      {data && (
        <div className="mt-3 space-y-3">
          {data.partial_matches.map((plan) => (
            <div key={plan.comicvine_volume_id} className="rounded-lg border border-[var(--theme-border)] p-2">
              <div className="text-xs font-medium text-[var(--theme-text-primary)]">
                {plan.actionable_reason}
              </div>
              <ul className="mt-1 space-y-1">
                {plan.matched.map((match) => (
                  <li key={`matched-${match.issue_id}`} className="flex items-center justify-between gap-2 text-xs text-[var(--theme-text-muted)]">
                    <span>
                      #{match.issue_number} → ComicVine #{match.comicvine_issue_id}
                    </span>
                    {match.mapping_id !== null && match.external_identity_id !== null && (
                      <button
                        type="button"
                        onClick={() => onConfirm(match.mapping_id!, match.external_identity_id!)}
                        className="px-2 py-0.5 text-xs font-medium rounded bg-[var(--theme-primary-action)] text-[var(--theme-primary-action-text)] hover:bg-[var(--theme-primary-action-hover)]"
                      >
                        Confirm
                      </button>
                    )}
                  </li>
                ))}
                {plan.unmatched.map((unmatched) => (
                  <li key={`unmatched-${unmatched.issue_id}`} className="text-xs text-[var(--theme-text-muted)]">
                    #{unmatched.issue_number}: {unmatched.reason}
                  </li>
                ))}
              </ul>
            </div>
          ))}

          {data.results.map((result) => (
            <div key={result.comicvine_issue_id} className="rounded-lg border border-[var(--theme-border)] p-2">
              <div className="flex items-center justify-between gap-2 text-xs text-[var(--theme-text-primary)]">
                <span>
                  #{result.issue_number ?? '?'} {result.volume_name ? `(${result.volume_name})` : ''}
                </span>
                {result.score !== null && (
                  <span className="text-[var(--theme-text-dim)]">
                    {Math.round(result.score * 100)}% match
                  </span>
                )}
              </div>
              {result.evidence.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {result.evidence.map((evidence, index) => (
                    <span
                      key={`${evidence}-${index}`}
                      className="text-[11px] text-[var(--theme-text-muted)] px-2 py-0.5 rounded border border-[var(--theme-border)]"
                    >
                      {evidence}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {data.partial_matches.length === 0 && data.results.length === 0 && (
            <p className="text-xs text-[var(--theme-text-muted)]">
              No matches found. Try another name, paste a URL, or map manually.
            </p>
          )}
        </div>
      )}
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
  const [showSearch, setShowSearch] = useState(false)

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

            {item.next_steps && item.next_steps.length > 0 && (
              <div className="mt-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-page)] p-2">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[var(--theme-text-muted)]">
                  Next steps
                </div>
                <ul className="mt-1 list-disc pl-4 text-xs text-[var(--theme-text-muted)]">
                  {item.next_steps.map((step, i) => (
                    <li key={`${step}-${i}`}>{step}</li>
                  ))}
                </ul>
              </div>
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

            {showSearch && (
              <MatchSearchPanel item={item} onConfirm={onConfirm} />
            )}

            <div className="flex gap-2 mt-3 pt-3 border-t border-[var(--theme-border)]">
              <button
                type="button"
                onClick={() => setShowSearch((visible) => !visible)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
              >
                {showSearch ? 'Hide search' : 'Find match'}
              </button>
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
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold mb-2 text-[var(--theme-text-primary)]">Identity Inbox</h1>
          <p className="text-sm text-[var(--theme-text-muted)]">
            Resolve unmatched or ambiguous external comic identities. Confirm the correct match,
            reject wrong candidates, or defer for later.
          </p>
        </div>
        <Link
          to="/duplicate-reconciliation"
          className="rounded-lg border border-[var(--theme-border)] px-3 py-2 text-sm text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)]"
        >
          Resolve duplicates
        </Link>
      </div>

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
