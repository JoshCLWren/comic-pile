import { useState, useEffect } from 'react'
import { issuesApi } from '../services/api-issues'
import type { Issue, Thread } from '../types'
import './IssueList.css'

interface IssueListProps {
  thread: Thread
  onThreadUpdated?: (threadId: number) => void
}

export function IssueList({ thread, onThreadUpdated }: IssueListProps) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [filter, setFilter] = useState<string>('all')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    loadIssues()
  }, [thread.id, filter])

  const loadIssues = async () => {
    setIsLoading(true)
    try {
      const response = await issuesApi.list(thread.id, {
        status: filter === 'all' ? undefined : (filter as 'unread' | 'read')
      })
      setIssues(response.issues)
    } catch (error) {
      console.error('Failed to load issues:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const toggleIssueStatus = async (issue: Issue) => {
    try {
      if (issue.status === 'read') {
        await issuesApi.markUnread(issue.id)
      } else {
        await issuesApi.markRead(issue.id)
      }

      if (onThreadUpdated) {
        onThreadUpdated(thread.id)
      }

      window.dispatchEvent(new CustomEvent('thread-updated', { detail: { threadId: thread.id } }))

      await loadIssues()
    } catch (error) {
      console.error('Failed to toggle issue status:', error)
    }
  }

  const getStatusIcon = (issue: Issue): string => {
    if (issue.status === 'read') return '✅'
    return '🟢'
  }

  if (isLoading) {
    return <div className="issue-list loading">Loading issues...</div>
  }

  if (issues.length === 0) {
    return <div className="issue-list empty">No issues found</div>
  }

  const nextUnreadId = thread.next_unread_issue_id
  const readCount = issues.filter((i) => i.status === 'read').length
  const progressPercent = Math.round((readCount / issues.length) * 100)

  return (
    <div className="issue-list">
      <div className="issue-list-header">
        <h3>Issues</h3>
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All</option>
          <option value="unread">Unread</option>
          <option value="read">Read</option>
        </select>
      </div>

      <div className="issues">
        {issues.map((issue) => (
          <div
            key={issue.id}
            className={`issue-item ${issue.status} ${issue.id === nextUnreadId ? 'next-unread' : ''}`}
            onClick={() => toggleIssueStatus(issue)}
          >
            <span className="issue-icon">{getStatusIcon(issue)}</span>
            <span className="issue-number">#{issue.issue_number}</span>
            {issue.id === nextUnreadId && <span className="next-badge">Next</span>}
            {issue.status === 'read' && issue.read_at && (
              <span className="read-date">{new Date(issue.read_at).toLocaleDateString()}</span>
            )}
          </div>
        ))}
      </div>

      <div className="issue-list-footer">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-text">
          Read {readCount} of {issues.length} ({progressPercent}%)
        </div>
      </div>
    </div>
  )
}
