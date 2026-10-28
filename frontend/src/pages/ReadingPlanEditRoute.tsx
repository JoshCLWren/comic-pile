import type { ReactNode } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { useReadingPlanReader } from '../hooks/useReadingPlans'

/**
 * Keep old edit bookmarks useful after the Option E single-authority cutover.
 *
 * A linked Plan must be edited through its owned Reading List. The legacy Plan
 * editor is only available when the reader explicitly reports legacy mode.
 * Failure to resolve the authority must never fall back to a stale Plan edit.
 */
export default function ReadingPlanEditRoute({ legacyEditor }: { legacyEditor: ReactNode }) {
  const { id } = useParams()
  const parsedId = Number(id)
  const planId = id && Number.isSafeInteger(parsedId) && parsedId > 0 ? parsedId : null
  const reader = useReadingPlanReader(planId)

  if (planId === null) {
    return <p role="alert">Invalid Reading Plan ID.</p>
  }

  if (reader.isPending) {
    return <p role="status">Opening the authoritative reading order…</p>
  }

  if (reader.isError || !reader.data) {
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
