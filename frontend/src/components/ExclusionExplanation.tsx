import { useState } from 'react'
import type { CreatorMetricIssue } from '../types/index'

interface ExclusionExplanationProps {
  excludedIssues: CreatorMetricIssue[]
  totalExcluded: number
}

export function ExclusionExplanation({ excludedIssues, totalExcluded }: ExclusionExplanationProps) {
  const [showExcluded, setShowExcluded] = useState(false)

  if (totalExcluded === 0) {
    return null
  }

  // Group excluded issues by reason
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
                  <div key={issue.issue_id} className="text-xs" style={{ color: 'var(--theme-text-muted)' }}>
                    • {issue.thread_title} #{issue.issue_number}
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