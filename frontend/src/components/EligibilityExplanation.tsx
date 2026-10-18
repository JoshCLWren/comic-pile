import { Link } from 'react-router-dom'
import type { BlockingDependency } from '../types'

interface Props {
  isBlocked: boolean
  reasons?: string[]
  dependencies?: BlockingDependency[]
  emptyLabel?: string
}

/** Render the backend decision without deriving eligibility from visible edges. */
export function EligibilityExplanation({ isBlocked, reasons = [], dependencies = [], emptyLabel = 'Available now' }: Props) {
  const labels = new Set(dependencies.map((dependency) => dependency.label))
  const remainingReasons = reasons.filter((reason) => !labels.has(reason))
  return (
    <div className="min-w-0 text-sm text-[var(--theme-text-muted)]" data-testid="eligibility-explanation">
      <p className="font-semibold">{isBlocked ? 'Waiting' : emptyLabel}</p>
      {(dependencies.length > 0 || remainingReasons.length > 0) && (
        <ul className="mt-1 space-y-1" aria-label="Reading requirements">
          {dependencies.map((dependency, index) => (
            <li key={`${dependency.issue_id ?? dependency.thread_id}-${index}`} className="break-words">
              <Link aria-label={`Open ${dependency.thread_title}${dependency.issue_id ? ` issue #${dependency.issue_number}` : ''}`}  to={`/thread/${dependency.thread_id}${dependency.issue_id ? `?issue=${dependency.issue_id}#issue-${dependency.issue_id}` : ''}`} className="text-[var(--theme-continuity-accent)] underline hover:text-[var(--theme-text-primary)]">
                {dependency.label}
              </Link>
            </li>
          ))}
          {remainingReasons.map((reason, index) => <li key={index} className="break-words">{reason}</li>)}
        </ul>
      )}
      {isBlocked && dependencies.length === 0 && reasons.length === 0 && <p>Reading requirements are unavailable. Open the series to retry.</p>}
    </div>
  )
}
