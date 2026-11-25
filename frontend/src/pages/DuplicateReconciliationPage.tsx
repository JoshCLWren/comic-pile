import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { issueDuplicateReconciliationApi } from '../services/api-issue-duplicate-reconciliation'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import { invalidateAfterDuplicateReconciliation } from '../query/cacheEffects'
import type {
  DuplicateCandidateGroup,
  DuplicateIssueEvidence,
  ReconcilePreviewResponse,
} from '../types'

function IssueEvidenceCard({
  evidence,
  label,
}: {
  evidence: DuplicateIssueEvidence
  label: string
}) {
  return (
    <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">{label}</span>
        <span className="text-xs text-[var(--theme-text-dim)]">ID {evidence.issue_id}</span>
      </div>
      <div className="text-sm font-semibold text-[var(--theme-text-primary)]">
        {evidence.thread_title} #{evidence.issue_number}
      </div>
      <div className="mt-2 grid gap-1 text-xs text-[var(--theme-text-muted)]">
        <div>Status: <span className="text-[var(--theme-text-primary)]">{evidence.status}</span></div>
        <div>Read at: <span className="text-[var(--theme-text-primary)]">{evidence.read_at ?? '—'}</span></div>
        <div>Created: <span className="text-[var(--theme-text-primary)]">{evidence.created_at}</span></div>
        <div>CV issue: <span className="text-[var(--theme-text-primary)]">{evidence.comicvine_issue_id ?? '—'}</span></div>
        <div>Ratings: <span className="text-[var(--theme-text-primary)]">{evidence.rating_events.length}</span></div>
        <div>Read events: <span className="text-[var(--theme-text-primary)]">{evidence.read_events.length}</span></div>
        <div>List memberships: <span className="text-[var(--theme-text-primary)]">{evidence.list_memberships.length}</span></div>
        {evidence.is_synthetic_placeholder_read && (
          <div className="mt-1 rounded bg-[var(--theme-danger)]/15 px-2 py-1 text-[var(--theme-danger)]">
            Invalid synthetic placeholder read (read_at before created_at)
          </div>
        )}
        {evidence.merged_into_issue_id != null && (
          <div className="mt-1 rounded bg-[var(--theme-comic-accent)]/15 px-2 py-1 text-[var(--theme-comic-accent)]">
            Merged into issue {evidence.merged_into_issue_id}
          </div>
        )}
      </div>
    </div>
  )
}

export default function DuplicateReconciliationPage() {
  const [selectedGroupKey, setSelectedGroupKey] = useState<string | null>(null)
  const [canonicalId, setCanonicalId] = useState<number | null>(null)
  const [duplicateIds, setDuplicateIds] = useState<number[]>([])
  const [preview, setPreview] = useState<ReconcilePreviewResponse | null>(null)
  const [decisions, setDecisions] = useState<Record<string, string>>({})
  const [lastUndoId, setLastUndoId] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const detectionsQuery = useQuery({
    queryKey: queryKeys.issueDuplicateReconciliation.detections(),
    queryFn: () => issueDuplicateReconciliationApi.detect(),
  })

  const previewMutation = useMutation({
    mutationFn: (nextDecisions: Record<string, string>) => {
      if (canonicalId == null || duplicateIds.length === 0) {
        throw new Error('Select canonical and duplicate issues')
      }
      return issueDuplicateReconciliationApi.preview({
        canonical_issue_id: canonicalId,
        duplicate_issue_ids: duplicateIds,
        decisions: nextDecisions,
      })
    },
    onSuccess: (data) => {
      setPreview(data)
      setMessage(null)
    },
    onError: (err) => {
      setMessage(err instanceof Error ? err.message : 'Preview failed')
    },
  })

  const applyMutation = useMutation({
    mutationFn: () => {
      if (!preview) throw new Error('Preview required')
      return issueDuplicateReconciliationApi.apply({
        canonical_issue_id: preview.canonical_issue_id,
        duplicate_issue_ids: preview.duplicate_issue_ids,
        decisions,
        preview_token: preview.preview_token,
      })
    },
    onSuccess: async (data) => {
      setMessage(`Reconciled. Undo ID: ${data.undo_snapshot_id ?? 'n/a'}`)
      setLastUndoId(data.undo_snapshot_id)
      setPreview(null)
      await invalidateAfterDuplicateReconciliation(queryClient)
    },
    onError: (err) => {
      setMessage(err instanceof Error ? err.message : 'Apply failed')
    },
  })

  const undoMutation = useMutation({
    mutationFn: (reconciliationId: number) =>
      issueDuplicateReconciliationApi.undo({ reconciliation_id: reconciliationId }),
    onSuccess: async (_data, reconciliationId) => {
      setMessage(`Undid reconciliation ${reconciliationId}`)
      setLastUndoId(null)
      await invalidateAfterDuplicateReconciliation(queryClient)
    },
    onError: (err) => {
      setMessage(err instanceof Error ? err.message : 'Undo failed')
    },
  })

  const groups = useMemo(
    () => detectionsQuery.data?.groups ?? [],
    [detectionsQuery.data],
  )
  const selectedGroup: DuplicateCandidateGroup | undefined = useMemo(
    () => groups.find((g) => g.group_key === selectedGroupKey),
    [groups, selectedGroupKey],
  )

  const selectGroup = (group: DuplicateCandidateGroup) => {
    setSelectedGroupKey(group.group_key)
    setCanonicalId(group.suggested_canonical_issue_id)
    setDuplicateIds(group.suggested_duplicate_issue_ids)
    setPreview(null)
    setDecisions({})
    setMessage(null)
  }

  const toggleDuplicate = (issueId: number) => {
    setPreview(null)
    setDuplicateIds((prev) =>
      prev.includes(issueId) ? prev.filter((id) => id !== issueId) : [...prev, issueId],
    )
  }

  return (
    <div className="mx-auto max-w-6xl p-4 sm:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Duplicate Comic Reconciliation</h1>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Detect, preview, and resolve duplicate physical issues with history-safe merges and undo.
        </p>
      </div>

      {message && (
        <div className="mb-4 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 text-sm text-[var(--theme-text-primary)]">
          {message}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <section className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">Detected groups</h2>
            <button
              type="button"
              className="text-xs text-[var(--theme-primary-action)]"
              onClick={() => detectionsQuery.refetch()}
            >
              Refresh
            </button>
          </div>
          {detectionsQuery.isPending && <div className="text-sm text-[var(--theme-text-muted)]">Loading…</div>}
          {detectionsQuery.isError && <div className="text-sm text-[var(--theme-danger)]">Failed to load detections.</div>}
          <div className="space-y-2">
            {groups.map((group) => (
              <button
                key={group.group_key}
                type="button"
                onClick={() => selectGroup(group)}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                  selectedGroupKey === group.group_key
                    ? 'border-[var(--theme-primary-action)] bg-[var(--theme-primary-action)]/10'
                    : 'border-[var(--theme-border)] bg-[var(--theme-bg-panel)]'
                }`}
              >
                <div className="font-medium text-[var(--theme-text-primary)]">{group.reason}</div>
                <div className="text-xs text-[var(--theme-text-dim)]">
                  {group.confidence} confidence · {group.evidence.length} issues
                </div>
              </button>
            ))}
            {!detectionsQuery.isPending && groups.length === 0 && (
              <div className="text-sm text-[var(--theme-text-muted)]">No duplicate groups detected.</div>
            )}
          </div>
        </section>

        <section className="space-y-4">
          {!selectedGroup && (
            <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-6 text-sm text-[var(--theme-text-muted)]">
              Select a detected group to preview reconciliation.
            </div>
          )}

          {selectedGroup && (
            <>
              <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
                <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">Resolve duplicate</h2>
                <p className="text-sm text-[var(--theme-text-muted)]">{selectedGroup.reason}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {selectedGroup.evidence.map((e) => (
                    <button
                      key={e.issue_id}
                      type="button"
                      onClick={() => {
                        setCanonicalId(e.issue_id)
                        setDuplicateIds(selectedGroup.evidence.filter((x) => x.issue_id !== e.issue_id).map((x) => x.issue_id))
                        setPreview(null)
                      }}
                      className={`rounded-full border px-3 py-1 text-xs ${
                        canonicalId === e.issue_id
                          ? 'border-[var(--theme-primary-action)] text-[var(--theme-primary-action)]'
                          : 'border-[var(--theme-border)] text-[var(--theme-text-muted)]'
                      }`}
                    >
                      Canonical: #{e.issue_number} ({e.issue_id})
                    </button>
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {selectedGroup.evidence.map((e) => (
                    <label key={e.issue_id} className="flex items-center gap-2 text-xs text-[var(--theme-text-muted)]">
                      <input
                        type="checkbox"
                        checked={duplicateIds.includes(e.issue_id)}
                        disabled={canonicalId === e.issue_id}
                        onChange={() => toggleDuplicate(e.issue_id)}
                      />
                      Duplicate: #{e.issue_number} ({e.issue_id})
                    </label>
                  ))}
                </div>
                <div className="mt-4 flex gap-2">
                  <button
                    type="button"
                    className="rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                    disabled={canonicalId == null || duplicateIds.length === 0 || previewMutation.isPending}
                    onClick={() => previewMutation.mutate(decisions)}
                  >
                    {previewMutation.isPending ? 'Previewing…' : 'Preview resolution'}
                  </button>
                  {lastUndoId != null && (
                    <button
                      type="button"
                      className="rounded-lg border border-[var(--theme-border)] px-4 py-2 text-sm text-[var(--theme-text-primary)]"
                      disabled={undoMutation.isPending}
                      onClick={() => undoMutation.mutate(lastUndoId)}
                    >
                      {undoMutation.isPending ? 'Undoing…' : `Undo #${lastUndoId}`}
                    </button>
                  )}
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                {selectedGroup.evidence.map((e) => (
                  <IssueEvidenceCard
                    key={e.issue_id}
                    evidence={e}
                    label={canonicalId === e.issue_id ? 'Canonical' : duplicateIds.includes(e.issue_id) ? 'Duplicate' : 'Related'}
                  />
                ))}
              </div>
            </>
          )}

          {preview && (
            <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4">
              <h3 className="mb-2 text-sm font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">Preview</h3>
              {preview.warnings.length > 0 && (
                <div className="mb-3 space-y-1">
                  {preview.warnings.map((w, i) => (
                    <div key={i} className="rounded bg-[var(--theme-comic-accent)]/10 px-3 py-2 text-xs text-[var(--theme-text-primary)]">{w}</div>
                  ))}
                </div>
              )}
              <div className="space-y-2">
                {preview.actions.map((action, i) => (
                  <div key={i} className="rounded border border-[var(--theme-border)] px-3 py-2 text-sm">
                    <div className="font-medium text-[var(--theme-text-primary)]">{action.kind}</div>
                    <div className="text-xs text-[var(--theme-text-muted)]">{action.description}</div>
                    {action.requires_decision && action.decision_key && (
                      <label className="mt-2 flex items-center gap-2 text-xs text-[var(--theme-text-muted)]">
                        <input
                          type="checkbox"
                          checked={decisions[action.decision_key] === 'merge'}
                          onChange={(e) => {
                            const next = {
                              ...decisions,
                              [action.decision_key!]: e.target.checked ? 'merge' : 'keep_distinct',
                            }
                            setDecisions(next)
                            previewMutation.mutate(next)
                          }}
                        />
                        Confirm merge despite warning
                      </label>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  className="rounded-lg bg-[var(--theme-danger)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                  disabled={!preview.can_apply || applyMutation.isPending}
                  onClick={() => applyMutation.mutate()}
                >
                  {applyMutation.isPending ? 'Applying…' : 'Apply reconciliation'}
                </button>
                <button
                  type="button"
                  className="rounded-lg border border-[var(--theme-border)] px-4 py-2 text-sm text-[var(--theme-text-primary)]"
                  onClick={() => setPreview(null)}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
