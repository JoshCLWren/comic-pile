import { useMemo, useState } from 'react'
import { useCommitSeriesMapping, useSiblingSeriesMappingPreview } from '../hooks/useSiblingSeriesMapping'
import {
  bulkApprovableSeriesMappingRows,
  isOwnedSeriesMappingRow,
} from '../services/api-series-mapping'
import type {
  SeriesMappingClassification,
  SeriesMappingPreviewRow,
} from '../services/api-series-mapping'
import { getApiErrorDetail } from '../utils/apiError'

interface SiblingSeriesMappingOfferProps {
  /** The corrected ComicPile issue whose confirmed volume licenses sibling scope. */
  originIssueId: number
  /** External provider name, for example `comicvine`. */
  provider: string
  /** The confirmed provider volume the siblings would map into. */
  providerSeriesExternalId: string
  /** Human-readable volume label shown before the preview resolves. */
  seriesLabel: string
  /** Called with the issue ids a commit actually confirmed. */
  onMapped: (confirmedIssueIds: number[]) => void
  /** Called when the reader finishes or declines the offer. */
  onDismiss: () => void
}

const STATUS_LABEL: Record<SeriesMappingClassification, string> = {
  already_confirmed: 'Linked',
  safe_exact_match: 'Exact match',
  needs_review_ambiguous: 'Needs review',
  needs_review_conflict: 'Conflict',
  unresolved: 'No match',
  excluded_special: 'Special',
}

const STATUS_ACCENT_CLASS: Record<SeriesMappingClassification, string> = {
  already_confirmed: 'border-[var(--theme-border)] text-[var(--theme-text-muted)]',
  safe_exact_match: 'border-[var(--theme-comic-accent)]/40 text-[var(--theme-comic-accent)]',
  needs_review_ambiguous: 'border-[var(--theme-warning)]/40 text-[var(--theme-warning)]',
  needs_review_conflict: 'border-[var(--theme-danger)]/40 text-[var(--theme-danger)]',
  unresolved: 'border-[var(--theme-border)] text-[var(--theme-text-dim)]',
  excluded_special: 'border-[var(--theme-border)] text-[var(--theme-text-dim)]',
}

/**
 * Commit refusals that mean the preview the reader approved is no longer current.
 *
 * The preview token is single-use in effect and expires, so these re-read the plan
 * instead of retrying a request the server will refuse again.
 */
const STALE_PREVIEW_DETAILS = new Set(['preview_expired', 'preview_stale'])

function issueNumberLabel(row: SeriesMappingPreviewRow): string {
  return row.issue_number ? `#${row.issue_number}` : 'Unnumbered'
}

/**
 * Offer to map the corrected issue's siblings into the same provider volume.
 *
 * Issue #3159: the sibling-scope logic already existed in the backend preview but
 * no surface surfaced it, so a reader who corrected one issue's volume never saw
 * the remaining numbered siblings that match. This renders that offer as a
 * read-only preview the reader approves in one step: exact sibling matches are
 * preselected, ambiguous or special numbers are reported but never preselected,
 * and provider inventory for issues the reader does not own is summarized rather
 * than listed.
 *
 * A failure here must never undo or hide the correction the reader already made,
 * so preview and commit failures stay inside this panel and always offer a way out.
 */
export default function SiblingSeriesMappingOffer({
  originIssueId,
  provider,
  providerSeriesExternalId,
  seriesLabel,
  onMapped,
  onDismiss,
}: SiblingSeriesMappingOfferProps) {
  const preview = useSiblingSeriesMappingPreview(
    originIssueId,
    provider,
    providerSeriesExternalId,
  )
  const commit = useCommitSeriesMapping()
  const [uncheckedRowIds, setUncheckedRowIds] = useState<ReadonlySet<string>>(() => new Set())

  const rows = useMemo(() => preview.data?.rows ?? [], [preview.data])
  const ownedRows = useMemo(() => rows.filter(isOwnedSeriesMappingRow), [rows])
  const approvableRows = useMemo(
    () => bulkApprovableSeriesMappingRows(rows).filter((row) => row.issue_id !== originIssueId),
    [rows, originIssueId],
  )
  const providerInventoryCount = rows.length - ownedRows.length

  const selectedRowIds = useMemo(
    () =>
      approvableRows
        .filter((row) => row.default_selected && !uncheckedRowIds.has(row.row_id))
        .map((row) => row.row_id),
    [approvableRows, uncheckedRowIds],
  )

  // The preview token is unique per preview and already embeds its issue time, so
  // deriving the key from it keeps one idempotency key across retries of the same
  // approval while a re-read preview naturally produces a fresh one.
  const previewToken = preview.data?.preview_token ?? null
  const idempotencyKey = previewToken
    ? `sibling-mapping-${originIssueId}-${preview.data?.issued_at ?? 0}`
    : null

  const commitErrorDetail = commit.isError ? getApiErrorDetail(commit.error) : null
  const previewIsStale = commitErrorDetail !== null && STALE_PREVIEW_DETAILS.has(commitErrorDetail)

  const commitMessage = (() => {
    if (!commit.isError) return null
    if (previewIsStale) {
      return 'That preview is out of date. Reviewing the series again.'
    }
    return 'Could not map the sibling issues. Nothing else was changed.'
  })()

  const toggleRow = (rowId: string, checked: boolean) => {
    setUncheckedRowIds((previous) => {
      const next = new Set(previous)
      if (checked) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      return next
    })
  }

  const approveSelected = () => {
    if (!previewToken || !idempotencyKey || selectedRowIds.length === 0) return
    commit.mutate(
      {
        preview_token: previewToken,
        idempotency_key: idempotencyKey,
        approved_row_ids: selectedRowIds,
      },
      {
        onSuccess: (result) => {
          onMapped(result.confirmed_issue_ids)
        },
        onError: (error) => {
          // A stale or expired preview cannot be re-committed, so re-read the plan
          // instead of leaving the reader with a dead approval.
          if (STALE_PREVIEW_DETAILS.has(getApiErrorDetail(error))) {
            commit.reset()
            setUncheckedRowIds(new Set())
            void preview.refetch()
          }
        },
      },
    )
  }

  if (preview.isPending) {
    return (
      <div className="space-y-4" data-testid="sibling-mapping-offer">
        <p className="text-sm text-stone-300">
          Checking the rest of <span className="font-bold text-stone-100">{seriesLabel}</span> for
          exact matches.
        </p>
        <div className="flex justify-center py-6">
          <div className="w-5 h-5 border-2 border-amber-500/30 border-t-amber-500 rounded-full animate-spin" />
        </div>
      </div>
    )
  }

  if (preview.isError) {
    return (
      <div className="space-y-4" data-testid="sibling-mapping-offer">
        <p role="alert" className="rounded-lg bg-stone-800/40 border border-stone-700/50 p-3 text-sm text-stone-300">
          {seriesLabel} was matched, but the remaining issues in the series could not be checked.
        </p>
        <button
          type="button"
          onClick={onDismiss}
          data-testid="sibling-mapping-dismiss"
          className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
        >
          Done
        </button>
      </div>
    )
  }

  if (approvableRows.length === 0) {
    return (
      <div className="space-y-4" data-testid="sibling-mapping-offer">
        <p className="text-sm text-stone-300">
          <span className="font-bold text-stone-100">{seriesLabel}</span> is linked for this issue.
          No other issue in the series matches that volume by number exactly.
        </p>
        <button
          type="button"
          onClick={onDismiss}
          data-testid="sibling-mapping-dismiss"
          className="w-full min-h-11 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition"
        >
          Done
        </button>
      </div>
    )
  }

  const selectedCount = selectedRowIds.length

  return (
    <div className="space-y-4" data-testid="sibling-mapping-offer">
      <section aria-label="Sibling mapping offer" className="space-y-3">
        <p className="text-sm text-stone-300">
          <span className="font-bold text-stone-100">{seriesLabel}</span> is now matched for this
          issue. The remaining issues in the series can use the same volume.
        </p>

        {commit.isSuccess && (
          <p
            role="status"
            className="rounded-lg border border-[var(--theme-primary-action)]/40 bg-stone-800/40 p-3 text-sm text-stone-100"
          >
            {commit.data.confirmed_issue_ids.length} sibling{' '}
            {commit.data.confirmed_issue_ids.length === 1 ? 'issue' : 'issues'} mapped to{' '}
            {seriesLabel}.
          </p>
        )}

        {commitMessage && (
          <p role="alert" className="rounded-lg bg-rose-900/30 border border-rose-700/40 p-3 text-sm text-rose-200">
            {commitMessage}
          </p>
        )}

        <ul className="space-y-2 max-h-72 overflow-y-auto overscroll-contain">
          {ownedRows.map((row) => {
            const isApprovable = approvableRows.some((candidate) => candidate.row_id === row.row_id)
            const checkboxId = `sibling-mapping-${row.row_id}`
            return (
              <li
                key={row.row_id}
                data-testid="sibling-mapping-row"
                data-classification={row.classification}
                className="flex items-center gap-3 rounded-xl bg-stone-800/50 border border-stone-700/50 p-3"
              >
                {isApprovable ? (
                  <input
                    id={checkboxId}
                    type="checkbox"
                    className="h-5 w-5 shrink-0 accent-amber-500"
                    checked={selectedRowIds.includes(row.row_id)}
                    onChange={(event) => toggleRow(row.row_id, event.target.checked)}
                  />
                ) : (
                  <span aria-hidden="true" className="h-5 w-5 shrink-0" />
                )}
                <label
                  htmlFor={isApprovable ? checkboxId : undefined}
                  className="min-w-0 flex-1 text-sm text-stone-100"
                >
                  <span className="font-bold">{issueNumberLabel(row)}</span>
                  {row.title ? <span className="text-stone-300"> {row.title}</span> : null}
                </label>
                <span
                  className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${STATUS_ACCENT_CLASS[row.classification]}`}
                >
                  {STATUS_LABEL[row.classification]}
                </span>
              </li>
            )
          })}
        </ul>

        {providerInventoryCount > 0 && (
          <p className="text-xs text-stone-500" data-testid="sibling-mapping-provider-inventory">
            {providerInventoryCount} other{' '}
            {providerInventoryCount === 1 ? 'issue is' : 'issues are'} in this volume but not in
            your library.
          </p>
        )}
      </section>

      <div className="flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          onClick={onDismiss}
          disabled={commit.isPending}
          data-testid="sibling-mapping-dismiss"
          className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-200 bg-stone-800/60 border border-stone-700/50 hover:bg-stone-800 transition disabled:opacity-50"
        >
          {commit.isSuccess ? 'Done' : 'Not now'}
        </button>
        <button
          type="button"
          onClick={approveSelected}
          disabled={commit.isPending || commit.isSuccess || selectedCount === 0}
          data-testid="sibling-mapping-approve"
          className="min-h-11 flex-1 rounded-xl px-4 text-sm font-bold text-stone-900 bg-amber-500 hover:bg-amber-400 transition disabled:opacity-50"
        >
          {commit.isPending
            ? 'Mapping...'
            : commit.isSuccess
              ? 'Mapped'
              : `Map ${selectedCount} ${selectedCount === 1 ? 'issue' : 'issues'}`}
        </button>
      </div>
    </div>
  )
}