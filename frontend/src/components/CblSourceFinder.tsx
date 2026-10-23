import { useState } from 'react'
import type { ReactNode } from 'react'
import Modal from './Modal'
import CblComparisonList from './CblComparisonList'
import {
  useCblComicvineIssueOccurrences,
  useCblIssueIdentity,
  useCblReadingListCandidates,
  useCblSourceComparison,
} from '../hooks/useCblSourceFinder'
import type { CBLSourceComparisonMatch } from '../services/api-cbl-sources'
import { displayCblSourceTitle } from '../utils/cblSourceDisplay'

interface FinderSurfaceProps {
  /** Router location to return to when the reader opens a source detail. */
  backTo: string
  /** Human label for the originating surface, echoed on the source page. */
  backLabel: string
  /** Stable test id prefix so both flows can be asserted independently. */
  testIdPrefix: string
}

interface CblComicFinderProps extends FinderSurfaceProps {
  /** Reader-owned Issue whose confirmed Comic Vine identity is looked up. */
  issueId: number
  /** Reader-facing label for the comic, e.g. `Ultimate Spider-Man #1`. */
  comicLabel: string
}

interface CblReadingListFinderProps extends FinderSurfaceProps {
  /** Owned Reading List ID. */
  listId: number
  /** Reader-facing Reading List name. */
  listName: string
}

/**
 * Render the shared error treatment for a failed CBL lookup.
 *
 * @param error - The failed query error.
 * @param retry - Re-runs the failed query.
 * @param message - Reader-facing fallback message.
 * @returns The error region.
 */
function LookupError({
  error,
  retry,
  message,
}: {
  error: unknown
  retry: () => void
  message: string
}) {
  const detail = error instanceof Error && error.message ? error.message : message
  return (
    <div className="space-y-2 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3">
      <p role="alert" className="text-sm text-[var(--theme-danger)]">
        {detail}
      </p>
      <button
        type="button"
        onClick={retry}
        className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
      >
        Retry
      </button>
    </div>
  )
}

/**
 * Render ranked candidate sources with an optional identity-gap summary.
 *
 * @param candidates - Ranked source comparisons.
 * @param inputTotal - Distinct confirmed input comics the coverage uses.
 * @param emptyMessage - Message shown when no source covers the input.
 * @param backTo - Router location to return to from a source detail.
 * @param backLabel - Human label for the originating surface.
 * @param testIdPrefix - Stable test id prefix.
 * @param gapSummary - Optional identity-gap summary shown above the results.
 * @returns The comparison results region.
 */
function CblComparisonResults({
  candidates,
  inputTotal,
  emptyMessage,
  backTo,
  backLabel,
  testIdPrefix,
  gapSummary,
}: FinderSurfaceProps & {
  candidates: CBLSourceComparisonMatch[]
  inputTotal: number
  emptyMessage: string
  gapSummary?: ReactNode
}) {
  return (
    <div className="space-y-3">
      {gapSummary}
      <CblComparisonList
        candidates={candidates}
        inputTotal={inputTotal}
        emptyMessage={emptyMessage}
        backTo={backTo}
        backLabel={backLabel}
        testIdPrefix={testIdPrefix}
      />
    </div>
  )
}

/**
 * Find the shared CBL source lists that hold one exact Comic Vine issue.
 *
 * The lookup starts from the comic's own confirmed Comic Vine identity. A
 * comic without exactly one confirmed identity reports that gap instead of
 * claiming that no CBL contains it, and every candidate links to the source
 * detail the reader can open next.
 *
 * @param props - Issue identity, reader-facing label, and navigation context.
 * @returns The "Find CBLs" action and its result dialog.
 */
export function CblComicFinder({
  issueId,
  comicLabel,
  backTo,
  backLabel,
  testIdPrefix,
}: CblComicFinderProps) {
  const [open, setOpen] = useState(false)
  const identityQuery = useCblIssueIdentity(issueId, open)
  const confirmedIds = (identityQuery.data?.confirmed_mappings ?? []).map(
    (mapping) => mapping.comicvine_id,
  )
  // Only exactly one confirmed identity may be compared. A conflicting pair is
  // a gap, never a guess about which identity the reader meant.
  const singleConfirmedId = confirmedIds.length === 1 ? confirmedIds[0] : null
  const comparisonQuery = useCblSourceComparison(
    singleConfirmedId ? [singleConfirmedId] : [],
    open,
  )
  const occurrenceQuery = useCblComicvineIssueOccurrences(singleConfirmedId, open)

  const occurrences = occurrenceQuery.data?.occurrences ?? []

  const renderResults = () => {
    if (identityQuery.isPending) {
      return (
        <p className="text-sm text-[var(--theme-text-muted)]">
          Checking this comic&apos;s Comic Vine identity…
        </p>
      )
    }
    if (identityQuery.isError) {
      return (
        <LookupError
          error={identityQuery.error}
          retry={() => void identityQuery.refetch()}
          message="Unable to read this comic's Comic Vine identity."
        />
      )
    }
    const confirmed = confirmedIds.length
    if (confirmed === 0) {
      return (
        <p className="text-sm text-[var(--theme-text-muted)]" data-testid={`${testIdPrefix}-identity-gap`}>
          ComicPile has no confirmed Comic Vine ID for {comicLabel}, so no CBL can be matched
          to this comic yet.
        </p>
      )
    }
    if (confirmed > 1) {
      return (
        <p className="text-sm text-[var(--theme-text-muted)]" data-testid={`${testIdPrefix}-identity-conflict`}>
          ComicPile has {confirmed} conflicting confirmed Comic Vine IDs for {comicLabel}.
          Resolve the identity before matching CBLs.
        </p>
      )
    }
    if (comparisonQuery.isPending) {
      return <p className="text-sm text-[var(--theme-text-muted)]">Searching CBL sources…</p>
    }
    if (comparisonQuery.isError) {
      return (
        <LookupError
          error={comparisonQuery.error}
          retry={() => void comparisonQuery.refetch()}
          message="Unable to compare CBL sources for this comic."
        />
      )
    }
    const candidates = comparisonQuery.data?.candidates ?? []
    return (
      <CblComparisonResults
        candidates={candidates}
        inputTotal={comparisonQuery.data?.input_total ?? 1}
        emptyMessage="No CBL source contains this comic's exact Comic Vine ID."
        backTo={backTo}
        backLabel={backLabel}
        testIdPrefix={testIdPrefix}
        gapSummary={
          occurrences.length > 0 ? (
            <section className="space-y-1" data-testid={`${testIdPrefix}-occurrences`}>
              <p className="text-xs text-[var(--theme-text-muted)]">
                {occurrenceQuery.data?.occurrences_total ?? occurrences.length} source position
                {(occurrenceQuery.data?.occurrences_total ?? occurrences.length) === 1 ? '' : 's'}{' '}
                in {occurrenceQuery.data?.lists_total ?? occurrences.length} source list
                {(occurrenceQuery.data?.lists_total ?? occurrences.length) === 1 ? '' : 's'} hold
                this exact issue.
              </p>
              <ul className="space-y-1 text-xs text-[var(--theme-text-dim)]">
                {occurrences.map((occurrence) => (
                  <li
                    key={`${occurrence.list_id}-${occurrence.position}`}
                    data-testid={`${testIdPrefix}-occurrence-${occurrence.list_id}`}
                  >
                    {displayCblSourceTitle(occurrence.list_name, occurrence.source_path) ??
                      occurrence.list_name}{' '}
                    · position {occurrence.position} · {occurrence.series_name} #
                    {occurrence.issue_number}
                  </li>
                ))}
              </ul>
            </section>
          ) : null
        }
      />
    )
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid={`${testIdPrefix}-open`}
        className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
      >
        Find CBLs
      </button>
      <Modal
        isOpen={open}
        title={`CBLs containing ${comicLabel}`}
        onClose={() => setOpen(false)}
        size="large"
      >
        <div className="space-y-3">{renderResults()}</div>
      </Modal>
    </>
  )
}

/**
 * Compare one owned Reading List against the shared CBL catalog.
 *
 * Entries without exactly one confirmed Comic Vine identity are reported as
 * gaps, and coverage is measured from the distinct confirmed identities only.
 * A list with no usable identity shows those gaps instead of a false "no CBL
 * covers this list" verdict.
 *
 * @param props - Reading List identity, name, and navigation context.
 * @returns The "Find CBLs" action and its results.
 */
export function CblReadingListFinder({
  listId,
  listName,
  backTo,
  backLabel,
  testIdPrefix,
}: CblReadingListFinderProps) {
  const [open, setOpen] = useState(false)
  const candidatesQuery = useCblReadingListCandidates(listId, open)

  const renderResults = () => {
    if (candidatesQuery.isPending) {
      return <p className="text-sm text-[var(--theme-text-muted)]">Comparing this Reading List…</p>
    }
    if (candidatesQuery.isError) {
      return (
        <LookupError
          error={candidatesQuery.error}
          retry={() => void candidatesQuery.refetch()}
          message="Unable to compare this Reading List with CBL sources."
        />
      )
    }
    const result = candidatesQuery.data
    const confirmedTotal = result?.input_confirmed_total ?? 0
    const missingCount = result?.input_missing_count ?? 0
    const conflictCount = result?.input_conflict_count ?? 0
    if (confirmedTotal === 0) {
      return (
        <p className="text-sm text-[var(--theme-text-muted)]" data-testid={`${testIdPrefix}-identity-gaps`}>
          None of {listName}&apos;s {result?.input_entry_count ?? 0} entries has exactly one
          confirmed Comic Vine ID ({missingCount} missing, {conflictCount} conflicting), so
          ComicPile cannot claim that no CBL covers this list.
        </p>
      )
    }
    const gapSummary =
      missingCount > 0 || conflictCount > 0 ? (
        <p
          className="text-xs text-[var(--theme-text-muted)]"
          data-testid={`${testIdPrefix}-gap-summary`}
        >
          Coverage uses the {confirmedTotal} confirmed Comic Vine issue
          {confirmedTotal === 1 ? '' : 's'}. {missingCount} entr
          {missingCount === 1 ? 'y has' : 'ies have'} no confirmed ID and {conflictCount} entr
          {conflictCount === 1 ? 'y has' : 'ies have'} conflicting IDs.
        </p>
      ) : null
    return (
      <CblComparisonResults
        candidates={result?.candidates ?? []}
        inputTotal={confirmedTotal}
        emptyMessage="No CBL source covers this list's confirmed comics."
        backTo={backTo}
        backLabel={backLabel}
        testIdPrefix={testIdPrefix}
        gapSummary={gapSummary}
      />
    )
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        data-testid={`${testIdPrefix}-open`}
        className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] hover:bg-white/5"
      >
        Find CBLs
      </button>
      {open && <div data-testid={`${testIdPrefix}-results`}>{renderResults()}</div>}
    </div>
  )
}

export default CblReadingListFinder
