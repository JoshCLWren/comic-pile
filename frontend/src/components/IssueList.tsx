import { useState, useEffect, useCallback, useRef } from 'react'
import { issuesApi } from '../services/api-issues'
import { issueDependenciesApi } from '../services/api-dependencies'
import type { ThreadIssueDependenciesResponse } from '../services/api-dependencies'
import type { Issue, IssueDependenciesResponse, IssueListResponse, Thread } from '../types'
import Tooltip from './Tooltip'
import { getDependencyTooltip } from '../utils/dependencyHelpers'

/** The issue-API surface IssueList consumes, injectable for tests. */
export interface IssueListApi {
  list: (
    threadId: number,
    params?: { status?: 'unread' | 'read'; page_size?: number; page_token?: string },
  ) => Promise<IssueListResponse>
  markRead: (issueId: number) => Promise<void>
  markUnread: (issueId: number) => Promise<void>
}

/** The dependency-API surface IssueList consumes, injectable for tests. */
export interface IssueListDependenciesApi {
  listForThread: (threadId: number) => Promise<ThreadIssueDependenciesResponse>
}

interface IssueListProps {
  thread: Thread
  onThreadUpdated?: (threadId: number) => void
  /** Injectable issue API; defaults to the production issuesApi. */
  issuesApi?: IssueListApi
  /** Injectable dependency API; defaults to the production issueDependenciesApi. */
  dependenciesApi?: IssueListDependenciesApi
}

export function IssueList({
  thread,
  onThreadUpdated,
  issuesApi: issuesService = issuesApi,
  dependenciesApi = issueDependenciesApi,
}: IssueListProps) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [filter, setFilter] = useState<'all' | 'unread' | 'read'>('all')
  const [isLoading, setIsLoading] = useState(true)
  const [isLoadingMore, setIsLoadingMore] = useState(false)
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [totalCount, setTotalCount] = useState<number>(0)
  const [dependencies, setDependencies] = useState<Record<number, IssueDependenciesResponse>>({})
  const filterRef = useRef<'all' | 'unread' | 'read'>('all')
  const threadIdRef = useRef(thread.id)
  const mountedRef = useRef(true)
  const issueLoadRequestRef = useRef(0)
  const dependencyLoadRequestRef = useRef(0)
  const issueMutationRequestRef = useRef<Record<number, number>>({})

  filterRef.current = filter
  threadIdRef.current = thread.id

  useEffect(() => {
    mountedRef.current = true

    return () => {
      mountedRef.current = false
      issueLoadRequestRef.current += 1
      dependencyLoadRequestRef.current += 1
    }
  }, [])

  const loadIssues = useCallback(async (append = false, pageToken?: string | null) => {
    const requestId = ++issueLoadRequestRef.current
    const requestedThreadId = thread.id
    const requestedFilter = filterRef.current

    if (append) {
      setIsLoadingMore(true)
    } else {
      setIsLoading(true)
    }

    try {
      const response = await issuesService.list(requestedThreadId, {
        status: requestedFilter === 'all' ? undefined : requestedFilter,
        page_size: 50,
        page_token: pageToken ?? undefined,
      })

      if (
        !mountedRef.current
        || requestId !== issueLoadRequestRef.current
        || requestedThreadId !== threadIdRef.current
        || requestedFilter !== filterRef.current
      ) {
        return
      }

      setIssues((previous) => append ? [...previous, ...response.issues] : response.issues)
      setTotalCount(response.total_count)
      setNextPageToken(response.next_page_token)
    } catch (error) {
      if (
        mountedRef.current
        && requestId === issueLoadRequestRef.current
        && requestedThreadId === threadIdRef.current
        && requestedFilter === filterRef.current
      ) {
        console.error('Failed to load issues:', error)
      }
    } finally {
      if (
        mountedRef.current
        && requestId === issueLoadRequestRef.current
        && requestedThreadId === threadIdRef.current
        && requestedFilter === filterRef.current
      ) {
        setIsLoading(false)
        setIsLoadingMore(false)
      }
    }
  }, [issuesService, thread.id])

  const loadDependencies = useCallback(async () => {
    const requestId = ++dependencyLoadRequestRef.current
    const requestedThreadId = thread.id
    setDependencies({})

    try {
      const response = await dependenciesApi.listForThread(requestedThreadId)

      if (
        !mountedRef.current
        || requestId !== dependencyLoadRequestRef.current
        || requestedThreadId !== threadIdRef.current
      ) {
        return
      }

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
      if (
        mountedRef.current
        && requestId === dependencyLoadRequestRef.current
        && requestedThreadId === threadIdRef.current
      ) {
        console.error(`Failed to load dependencies for thread ${requestedThreadId}:`, error)
      }
    }
  }, [dependenciesApi, thread.id])

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
    const mutationThreadId = thread.id
    const mutationFilter = filterRef.current
    const mutationRequestId = (issueMutationRequestRef.current[issue.id] ?? 0) + 1
    const originalIndex = issues.findIndex((currentIssue) => currentIssue.id === issue.id)
    const nextStatus = issue.status === 'read' ? 'unread' : 'read'
    const shouldRemoveFromFilter = mutationFilter !== 'all' && mutationFilter !== nextStatus
    const updatedIssue: Issue = {
      ...issue,
      status: nextStatus,
      read_at: nextStatus === 'read' ? new Date().toISOString() : null,
    }

    issueMutationRequestRef.current[issue.id] = mutationRequestId

    setIssues((currentIssues) => {
      if (shouldRemoveFromFilter) {
        return currentIssues.filter((currentIssue) => currentIssue.id !== issue.id)
      }

      return currentIssues.map((currentIssue) =>
        currentIssue.id === issue.id ? updatedIssue : currentIssue
      )
    })

    if (shouldRemoveFromFilter) {
      setTotalCount((currentTotal) => Math.max(0, currentTotal - 1))
    }

    try {
      if (issue.status === 'read') {
        await issuesService.markUnread(issue.id)
      } else {
        await issuesService.markRead(issue.id)
      }

      onThreadUpdated?.(mutationThreadId)
      window.dispatchEvent(new CustomEvent('thread-updated', { detail: { threadId: mutationThreadId } }))
    } catch (error) {
      console.error('Failed to toggle issue status:', error)

      if (
        issueMutationRequestRef.current[issue.id] !== mutationRequestId
        || threadIdRef.current !== mutationThreadId
        || filterRef.current !== mutationFilter
      ) {
        return
      }

      setIssues((currentIssues) => {
        const existingIndex = currentIssues.findIndex(
          (currentIssue) => currentIssue.id === issue.id,
        )

        if (existingIndex >= 0) {
          return currentIssues.map((currentIssue) =>
            currentIssue.id === issue.id ? issue : currentIssue
          )
        }

        const insertionIndex = Math.max(0, Math.min(originalIndex, currentIssues.length))
        return [
          ...currentIssues.slice(0, insertionIndex),
          issue,
          ...currentIssues.slice(insertionIndex),
        ]
      })

      if (shouldRemoveFromFilter) {
        setTotalCount((currentTotal) => currentTotal + 1)
      }
    }
  }

  const getStatusIcon = (issue: Issue): string => {
    if (issue.status === 'read') return '✅'
    return '🟢'
  }

  if (isLoading) {
    return (
      <div className="border border-[var(--theme-border)] rounded-lg p-8 text-center text-[var(--theme-text-muted)]">
        Loading issues...
      </div>
    )
  }

  if (issues.length === 0) {
    return (
      <div className="border border-[var(--theme-border)] rounded-lg p-8 text-center text-[var(--theme-text-muted)]">
        No issues found
      </div>
    )
  }

  const nextUnreadId = thread.next_unread_issue_id
  const readCount = issues.filter((issue) => issue.status === 'read').length
  const progressPercent = totalCount > 0 ? Math.round((readCount / totalCount) * 100) : 0

  return (
    <div className="border border-[var(--theme-border)] rounded-lg p-4">
      <div className="flex justify-between items-center mb-4">
        <h3 className="m-0 text-lg">Issues</h3>
        <select
          value={filter}
          // SAFETY: the select options are exactly the FilterType union values, so the event value is one of them.
          onChange={(event) => handleFilterChange(event.target.value as 'all' | 'unread' | 'read')}
          className="px-2 py-1 border border-[var(--theme-border)] rounded-md"
        >
          <option value="all">All</option>
          <option value="unread">Unread</option>
          <option value="read">Read</option>
        </select>
      </div>

      <div className="flex flex-col gap-2">
        {issues.map((issue) => {
          const hasDependencies = dependencies[issue.id] !== undefined
          const tooltipContent = getDependencyTooltip(dependencies[issue.id])

          return (
            <div
              key={issue.id}
              className={`flex items-center gap-2 p-2 rounded-md cursor-pointer transition-colors hover:[var(--theme-bg-panel)] ${
                issue.id === nextUnreadId 
                  ? 'bg-[color-mix(in_srgb,var(--theme-comic-accent)_15%,transparent)] border border-[var(--theme-comic-accent)]' 
                  : ''
              }`}
              onClick={() => toggleIssueStatus(issue)}
            >
              <span className="text-lg">{getStatusIcon(issue)}</span>
              <span className="font-medium">#{issue.issue_number}</span>
              {hasDependencies && tooltipContent && (
                <Tooltip content={tooltipContent}>
                  <span
                    className="text-sm cursor-help ml-1 opacity-70 transition-opacity hover:opacity-100"
                    onClick={(event) => event.stopPropagation()}
                    title="Has dependencies"
                  >
                    🔗
                  </span>
                </Tooltip>
              )}
              {issue.id === nextUnreadId && (
                <span className="ml-auto bg-[var(--theme-comic-accent)] text-white px-2 py-1 rounded-full text-xs font-medium">
                  Next
                </span>
              )}
              {issue.status === 'read' && issue.read_at && (
                <span className="ml-auto text-sm text-[var(--theme-text-muted)]">
                  {new Date(issue.read_at).toLocaleDateString()}
                </span>
              )}
            </div>
          )
        })}
      </div>

      {nextPageToken && (
        <div className="mb-4">
          <button
            type="button"
            onClick={() => loadIssues(true, nextPageToken)}
            disabled={isLoadingMore}
            className="w-full px-4 py-2 border border-[var(--theme-border)] rounded-md hover:[var(--theme-bg-panel)] transition-colors disabled:opacity-50"
          >
            {isLoadingMore ? 'Loading...' : `Load more (${issues.length} of ${totalCount})`}
          </button>
        </div>
      )}

      <div className="mt-4">
        <div className="h-2 bg-[var(--theme-border)] rounded-full overflow-hidden">
          <div 
            className="h-full bg-[var(--theme-comic-accent)] transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="mt-1 text-sm text-[var(--theme-text-muted)] text-center">
          Read {readCount} of {totalCount} ({progressPercent}%)
        </div>
      </div>
    </div>
  )
}
