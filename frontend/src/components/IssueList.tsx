import { Link } from 'react-router-dom'
import type { CreatorMetricIssue } from '../types/index'

interface IssueListProps {
  issues: CreatorMetricIssue[]
}

export function IssueList({ issues }: IssueListProps) {
  if (issues.length === 0) {
    return (
      <div className="surface-panel rounded-xl p-6 border text-center" style={{ borderColor: 'var(--theme-border)' }}>
        <p className="text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          No issues found for this metric.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {issues.map((issue) => (
        <div
          key={issue.issue_id}
          className="surface-panel rounded-lg p-3 border flex items-start gap-3"
          style={{ borderColor: 'var(--theme-border)' }}
        >
          <div className="flex-shrink-0">
            <div
              className={`w-2 h-2 rounded-full mt-2 ${
                issue.status === 'read' ? 'bg-green-500' : 'bg-gray-400'
              }`}
            />
          </div>
          
          <div className="flex-1 min-w-0">
            <Link
              to={`/thread/${issue.thread_id}`}
              className="block hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] rounded"
              style={{ color: 'var(--theme-text-primary)' }}
            >
              <div className="font-semibold truncate">{issue.thread_title}</div>
              <div className="text-sm mt-1">
                #{issue.issue_number}
              </div>
            </Link>
            
            <div className="mt-2 flex flex-wrap gap-2">
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                  issue.status === 'read'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-800'
                }`}
              >
                {issue.status === 'read' ? 'Read' : 'Unread'}
              </span>
              
              {issue.effective_rating && (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--theme-personal-accent)',
                    color: 'white',
                  }}
                >
                  {issue.effective_rating}★
                </span>
              )}
              
              {issue.creator_roles.length > 0 && (
                <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--theme-bg-panel)',
                    color: 'var(--theme-text-primary)',
                    borderColor: 'var(--theme-border)',
                    borderWidth: '1px',
                    borderStyle: 'solid',
                  }}
                >
                  {issue.creator_roles.join(', ')}
                </span>
              )}
              
              {issue.exclusion_reason && (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                  style={{
                    backgroundColor: 'var(--theme-warning)',
                    color: 'var(--theme-text-primary)',
                  }}
                >
                  {issue.exclusion_reason}
                </span>
              )}
            </div>
            
            {issue.effective_rating_source && (
              <div className="mt-2 text-xs" style={{ color: 'var(--theme-text-dim)' }}>
                Rating source: {issue.effective_rating_source}
                {issue.effective_rating_timestamp && (
                  <span className="ml-2">
                    {new Date(issue.effective_rating_timestamp).toLocaleDateString()}
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}