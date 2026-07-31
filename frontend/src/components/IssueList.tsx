import { useState, useEffect, useCallback, useRef } from 'react'
import { issuesApi } from '../services/api-issues'
import { issueDependenciesApi } from '../services/api-dependencies'
import type { Issue, IssueDependenciesResponse, Thread } from '../types'
import Tooltip from './Tooltip'
import { getDependencyTooltip } from '../utils/dependencyHelpers'
import './IssueList.css'

interface IssueListProps {
  thread: Thread
  onThreadUpdated?: (threadId: number) => void
}

export function IssueList({ thread, onThreadUpdated }: IssueListProps) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [filter, setFilter] = useState<'all' | 'unread' | 'read'>('all')
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [totalCount, setTotalCount] = useState<number>(0)
  const [dependencies, setDependencies] = useState<Record<number, IssueDependenciesResponse>>({})
  const filterRef = useRef<'all' | 'unread' | 'read'>('all')
  filterRef.current = filter

  const loadIssues = useCallback(async (append = false, pageToken?: string | null) => {
    if (append) {
      setIsLoadingMore(true)
    } else {
      setIsLoading(true)
    }

    try {
      const response = await issuesApi.list(thread.id, {
        status: filterRef.current === 'all' ? undefined : filterRef.current,
        page_size: 50,
        page_token: pageToken ?? undefined,
      })

      setIssues((previous) => append ? [...previous, ...response.issues] : response.issues)
      setTotalCount(response.total_count)
      setNextPageToken(response.next_page_token)
    } catch (error) {
      console.error('Failed to load issues:', error)
    } finally {
      setIsLoading(false)
      setIsLoadingMore(false)
    }
  }, [thread.id])

  const loadDependencies = useCallback(async () => {
    setDependencies({})

    try {
      const response = await issueDependenciesApi.listForThread(thread.id)
      const nextDependencies: Record<number, IssueDependenciesResponse> = {}

      for (const issueDependencies of response.issues) {
        if (
          issueDependencies.incoming.length > 0
          || issueDependencies.outgoing.length > 0
        ) {
          nextDependencies[issueDependencies.issue_id] = issueDependencies
        }
      }

      setDependencies(nextDependencies)
    } catch (error) {
      console.error(`Failed to load dependencies for thread ${thread.id}:`, error)
    }
  }, [thread.id])

  useEffect(() => {
    void Promise.all([loadIssues(false), loadDependencies()])
  }, [loadDependencies, loadIssues])

  const handleFilterChange = (newFilter: 'all' | 'unread' | 'read') => {
    filterRef.current = newFilter
    setFilter(newFilter)
    setNextPageToken(null)
    void loadIssues(false)
  }

  const toggleIssueStatus = async (issue: Issue) => {
    const previousIssues = issues
    const previousTotalCount = totalCount
    const nextStatus = issue.status === 'read' ? 'unread' : 'read'
    const updatedIssue: Issue = {
      ...issue,
      status: nextStatus,
      read_at: nextStatus === 'read' ? new Date().toISOString() : null,
    }

    setIssues((currentIssues) => {
      if (filterRef.current !== 'all' && filterRef.current !== nextStatus) {
        return currentIssues.filter((currentIssue) => currentIssue.id !== issue.id)
      }

      return currentIssues.map((currentIssue) =>
        currentIssue.id === issue.id ? updatedIssue : currentIssue
      )
    })

    if (filterRef.current !== 'all' && filterRef.current !== nextStatus) {
      setTotalCount((currentTotal) => Math.max(0, currentTotal - 1))
    }

    try {
      if (issue.status === 'read') {
        await issuesApi.markUnread(issue.id)
      } else {
        await issuesApi.markRead(issue.id)
      }

      onThreadUpdated?.(thread.id)
      window.dispatchEvent(new CustomEvent('thread-updated', { detail: { threadId: thread.id } }))
    } catch (error) {
      setIssues(previousIssues)
      setTotalCount(previousTotalCount)
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
  const readCount = issues.filter((issue) => issue.status === 'read').length
  const progressPercent = totalCount > 0 ? Math.round((readCount / totalCount) * 100) : 0

  return (
    <div className="issue-list">
      <div className="issue-list-header">
        <h3>Issues</h3>
        <select
          value={filter}
          onChange={(event) => handleFilterChange(event.target.value as 'all' | 'unread' | 'read')}
        >
          <option value="all">All</option>
          <option value="unread">Unread</option>
          <option value="read">Read</option>
        </select>
      </div>

      <div className="issues">
        {issues.map((issue) => {
          const hasDependencies = dependencies[issue.id] !== undefined
          const tooltipContent = getDependencyTooltip(dependencies[issue.id])

          return (
            <div
              key={issue.id}
              className={`issue-item ${issue.status} ${issue.id === nextUnreadId ? 'next-unread' : ''}`}
              onClick={() => toggleIssueStatus(issue)}
            >
              <span className="issue-icon">{getStatusIcon(issue)}</span>
              <span className="issue-number">#{issue.issue_number}</span>
              {hasDependencies && tooltipContent && (
                <Tooltip content={tooltipContent}>
                  <span
                    className="dependency-indicator"
                    onClick={(event) => event.stopPropagation()}
                    title="Has dependencies"
                  >
                    🔗
                  </span>
                </Tooltip>
              )}
              {issue.id === nextUnreadId && <span className="next-badge">Next</span>}
              {issue.status === 'read' && issue.read_at && (
                <span className="read-date">{new Date(issue.read_at).toLocaleDateString()}</span>
              )}
            </div>
          )
        })}
      </div>

      {nextPageToken && (
        <div className="issue-list-load-more">
          <button
            type="button"
            onClick={() => loadIssues(true, nextPageToken)}
            disabled={isLoadingMore}
            className="load-more-button"
          >
            {isLoadingMore ? 'Loading...' : `Load more (${issues.length} of ${totalCount})`}
          </button>
        </div>
      )}

      <div className="issue-list-footer">
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${progressPercent}%` }} />
        </div>
        <div className="progress-text">
          Read {readCount} of {totalCount} ({progressPercent}%)
        </div>
      </div>
    </div>
  )
}
