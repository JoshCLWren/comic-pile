import { useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { issuesApi } from '../../services/api-issues'
import { getApiErrorDetail } from '../../utils/apiError'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../../query/cacheEffects'
import { queryClient } from '../../query/queryClient'
import type { ThreadListItem } from '../../types'
import { useToast } from '../../contexts/useToast'

export type QueueCompletedSeriesMatch = { id: number; title: string; status: 'completed' | 'excluded' }

export function useQueueCompletedSeriesSearch(
  completedThreads: ThreadListItem[] | undefined,
  excludedThreads: ThreadListItem[] | undefined,
  isSearching: boolean,
  searchQuery: string,
) {
  const navigate = useNavigate()
  const { showToast } = useToast()
  const client = useQueryClient()

  const normalizedSearch = searchQuery.trim().toLowerCase()

  const completedMatches = useMemo(
    () =>
      isSearching
        ? (completedThreads ?? [])
            .filter((t) => t.title.toLowerCase().includes(normalizedSearch))
            .map((t) => ({ id: t.id, title: t.title, status: 'completed' as const }))
        : [],
    [completedThreads, isSearching, normalizedSearch],
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

  const handleRestoreCompletedSeries = useCallback(
    async (threadId: number) => {
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
    },
    [showToast],
  )

  const handleOpenCompletedSeries = useCallback((id: number) => navigate(`/thread/${id}`), [navigate])
  const handleOpenExcludedSeries = useCallback((id: number) => navigate(`/thread/${id}`), [navigate])

  return {
    completedMatches,
    excludedMatches,
    handleRestoreCompletedSeries,
    handleOpenCompletedSeries,
    handleOpenExcludedSeries,
  }
}