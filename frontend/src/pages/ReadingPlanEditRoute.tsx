import type { ReactNode } from 'react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useReadingPlanReader, useReadingPlanRecoveryPreview } from '../hooks/useReadingPlans'

/**
 * Keep old edit bookmarks useful after the Option E single-authority cutover.
 *
 * A linked Plan must be edited through its owned Reading List. The legacy Plan
 * editor is available when the reader reports legacy mode, or when the owner
 * follows the recovery screen's explicit authoring link (?authoring=1) and the
 * recovery preview confirms the plan is orphaned. A relinked, ambiguous, or
 * transiently failing reader never unlocks a stale Plan edit.
 */
export default function ReadingPlanEditRoute({ legacyEditor }: { legacyEditor: ReactNode }) {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const authoring = searchParams.get('authoring') === '1'
  const parsedId = Number(id)
  const planId = id && Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const reader = useReadingPlanReader(planId)
  // An authoring link is only a fallback when the plan is actually orphaned.
  // Confirm with the recovery preview so a relinked, ambiguous, or temporarily
  // failing reader never unlocks the stale editor (and its authority-erasing
  // save path).
  const recovery = useReadingPlanRecoveryPreview(
    authoring && reader.isError ? planId : null,
  )

  if (planId === null) {
    return <p role="alert">Invalid Reading Plan ID.</p>
  }

  if (reader.isPending) {
    return <p role="status">Opening the authoritative reading order…</p>
  }

  if (reader.isError || !reader.data) {
    // The recovery screen explicitly offers authoring as an alternative to
    // relinking an orphaned plan. That link opts into the legacy editor, which
    // loads the owned Plan directly and can save a fresh authored order. A
    // linked Option E plan still resolves below and is sent to its List.
    if (authoring && recovery.isPending) {
      return <p role="status">Checking Reading Plan recovery state…</p>
    }
    if (authoring && recovery.data?.status === 'orphaned') {
      return <>{legacyEditor}</>
    }
    return (
      <div role="alert">
        Could not determine this Plan's reading-order authority. No legacy edits were made.{' '}
        <Link to={'/continuity-plans/' + planId}>Return to Reading Plan</Link>
      </div>
    )
  }

  if (reader.data.execution_mode === 'legacy') {
    return <>{legacyEditor}</>
  }

  if (reader.data.execution_mode !== 'option_e') {
    return (
      <div role="alert">
        The Reading Plan's execution mode could not be verified. The obsolete Plan editor is unavailable.{' '}
        <Link to={'/continuity-plans/' + planId}>Return to Reading Plan</Link>
      </div>
    )
  }

  // The reader only supplies display_name for an owned List source. Never
  // guess a List from the Plan name or a historic, foreign source ID.
  const ownedSource = reader.data.sources.find(
    (source) => source.display_name != null && /^custom-cbl:[1-9][0-9]*$/.test(source.raw_source_path),
  )
  const listId = ownedSource
    ? Number(ownedSource.raw_source_path.slice('custom-cbl:'.length))
    : null
  if (listId !== null && Number.isSafeInteger(listId) && listId > 0) {
    return <Navigate to={'/reading-lists/' + listId} replace />
  }

  return (
    <div role="alert">
      This Plan uses an authoritative Reading List, but its owned List could not be resolved.
      The obsolete Plan editor is unavailable.{' '}
      <Link to={'/continuity-plans/' + planId}>Return to Reading Plan</Link>
    </div>
  )
}
