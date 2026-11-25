import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useToast } from '../../contexts/useToast'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import { issuesApi } from '../../services/api-issues'
import { getApiErrorDetail } from '../../utils/apiError'
import { useCompletedThreads } from './useCompletedThreads'
import { useExcludedThreads } from './useExcludedThreads'

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
      const allIssues: number[] = []
      let pageToken: string | undefined
      do {
        const page = await issuesApi.list(threadId, { status: 'read', page_size: 100, page_token: pageToken })
        allIssues.push(...page.issues.map((i) => i.id))
        pageToken = page.next_page_token ?? undefined
      } while (pageToken)
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
