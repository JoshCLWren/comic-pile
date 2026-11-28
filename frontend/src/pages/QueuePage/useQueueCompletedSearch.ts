import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../../contexts/useToast'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { issuesApi } from '../../services/api-issues'
import { getApiErrorDetail } from '../../utils/apiError'
import { useCompletedThreads } from '../../hooks/useCompletedThreads'
import { useExcludedThreads } from '../../hooks/useQueue'
import { collectAllPages, MAX_ISSUE_COLLECTION_PAGES } from '../../pagination/collectAllPages'

export interface CompletedSeriesMatch {
  id: number
  title: string
  status: 'completed'
}

export interface ExcludedSeriesMatch {
  id: number
  title: string
  status: 'excluded'
}

export interface QueueCompletedSearchResult {
  isSearching: boolean
  completedMatches: CompletedSeriesMatch[]
  excludedMatches: ExcludedSeriesMatch[]
  handleRestoreCompletedSeries: (threadId: number) => Promise<void>
  openCompletedSeries: (id: number) => void
  openExcludedSeries: (id: number) => void
}

export function useQueueCompletedSearch(
  searchQuery: string,
): QueueCompletedSearchResult {
  const { showToast } = useToast()
  const navigate = useNavigate()
  const isSearching = searchQuery.trim() !== ''
  const normalizedSearch = searchQuery.trim().toLowerCase()
  const completed = useCompletedThreads()
  const { threads: excludedThreads } = useExcludedThreads(true)

  const completedMatches = useMemo(
    () =>
      isSearching
        ? (completed.threads ?? [])
            .filter((t) => t.title.toLowerCase().includes(normalizedSearch))
            .map((t) => ({ id: t.id, title: t.title, status: 'completed' as const }))
        : [],
    [completed.threads, isSearching, normalizedSearch],
  )
  const excludedMatches = useMemo(
    () =>
      isSearching
        ? (excludedThreads ?? [])
            .filter((t) => t.title.toLowerCase().includes(normalizedSearch))
            .map((t) => ({ id: t.id, title: t.title, status: 'excluded' as const }))
        : [],
    [excludedThreads, isSearching, normalizedSearch],
  )

  const handleRestoreCompletedSeries = useCallback(async (threadId: number) => {
    try {
      const collected = await collectAllPages({
        fetchPage: (token) => issuesApi.list(threadId, {
          status: 'read', page_size: 100, page_token: token ?? undefined,
        }),
        selectItems: (page) => page.issues.map((issue) => issue.id),
        selectNextToken: (page) => page.next_page_token || null,
        maxPages: MAX_ISSUE_COLLECTION_PAGES,
      })
      if (collected.stopReason === 'max-pages') {
        throw new Error('Unable to load every read issue for this series.')
      }
      const allIssues = collected.items
      if (allIssues.length === 0) {
        showToast('No read issues to restore', 'info')
        return
      }
      await issuesApi.bulkMarkUnread(allIssues)
      await invalidateAfterQueueMutation(queryClient)
      await invalidateAfterIssueEdit(queryClient, threadId)
      showToast('Restored series issues to unread', 'success')
    } catch (e) {
      showToast(`Failed to restore unread: ${getApiErrorDetail(e)}`, 'error')
    }
  }, [showToast])

  const openCompletedSeries = useCallback((id: number) => navigate(`/thread/${id}`), [navigate])
  const openExcludedSeries = useCallback((id: number) => navigate(`/thread/${id}`), [navigate])

  return {
    isSearching,
    completedMatches,
    excludedMatches,
    handleRestoreCompletedSeries,
    openCompletedSeries,
    openExcludedSeries,
  }
}
