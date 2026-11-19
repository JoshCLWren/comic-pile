import { useMemo, useState } from 'react'
import type { CreatorMetricIssue } from '../types/index'
import CompactIssueCardTrigger from './CompactIssueCardTrigger'
import { useIssueCards, indexIssueCards } from '../hooks/useIssueCards'

interface ExclusionExplanationProps {
  excludedIssues: CreatorMetricIssue[]
  totalExcluded: number
}

export function ExclusionExplanation({ excludedIssues, totalExcluded }: ExclusionExplanationProps) {
  const [showExcluded, setShowExcluded] = useState(false)
  // Bounded batch for the rows the reader can actually see (five per reason);
  // nothing fetches while the list stays collapsed. Hooks run before the early
  // return so hook order never changes.
  const visibleIssueIds = useMemo(
    () => {
      if (!showExcluded) return []
      const byReason = new Map<string, CreatorMetricIssue[]>()
      for (const issue of excludedIssues) {
        const reason = issue.exclusion_reason || 'No specific reason'
        const bucket = byReason.get(reason) ?? []
        if (bucket.length < 5) bucket.push(issue)
        byReason.set(reason, bucket)
      }
      return Array.from(byReason.values()).flat().map((issue) => issue.issue_id)
    },
    [excludedIssues, showExcluded],
  )
  const cardsQuery = useIssueCards(visibleIssueIds, { enabled: showExcluded })
  const cardsByIssue = useMemo(() => indexIssueCards(cardsQuery.data), [cardsQuery.data])

  if (totalExcluded === 0) {
    return null
  }

  // Group excluded issues by reason.
  // SAFETY: the accumulator starts as an empty object and only gains string keys mapped to CreatorMetricIssue arrays, so it is exactly Record<string, CreatorMetricIssue[]>.
  const exclusionGroups = excludedIssues.reduce((acc, issue) => {
    const reason = issue.exclusion_reason || 'No specific reason'
    if (!acc[reason]) {
      acc[reason] = []
    }
    acc[reason].push(issue)
    return acc
  }, {} as Record<string, CreatorMetricIssue[]>)

  return (
    <div className="surface-panel rounded-xl p-4 border" style={{ borderColor: 'var(--theme-border)' }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide" style={{ color: 'var(--theme-text-dim)' }}>
          Excluded Issues
        </h3>
        <span className="text-sm font-semibold" style={{ color: 'var(--theme-text-primary)' }}>
          {totalExcluded} not included
        </span>
      </div>

      <p className="text-sm mb-3" style={{ color: 'var(--theme-text-muted)' }}>
        These issues are not included in the calculation for the following reasons:
      </p>

      <div className="space-y-3">
        {Object.entries(exclusionGroups).map(([reason, issues]) => (
          <div key={reason} className="border-l-2 pl-3" style={{ borderColor: 'var(--theme-warning)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium" style={{ color: 'var(--theme-text-primary)' }}>
                {reason}
              </span>
              <span className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                {issues.length} issue{issues.length !== 1 ? 's' : ''}
              </span>
            </div>
            
            {showExcluded && (
              <div className="space-y-1">
                {issues.slice(0, 5).map((issue) => (
                  <div key={issue.issue_id} className="flex items-center gap-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                    <CompactIssueCardTrigger
                      issueId={issue.issue_id}
                      threadTitle={issue.thread_title}
                      issueNumber={issue.issue_number}
                      status={issue.status === 'read' ? 'read' : 'unread'}
                      rating={issue.effective_rating}
                      card={cardsByIssue.get(issue.issue_id) ?? null}
                      hideTitle
                    />
                    <span className="min-w-0 truncate">• {issue.thread_title} #{issue.issue_number}</span>
                  </div>
                ))}
                {issues.length > 5 && (
                  <div className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                    ... and {issues.length - 5} more
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <button
        onClick={() => setShowExcluded(!showExcluded)}
        className="mt-3 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] rounded"
        style={{ color: 'var(--theme-primary-action)' }}
      >
        {showExcluded ? 'Hide excluded issues' : 'Show excluded issues'}
      </button>
    </div>
  )
}