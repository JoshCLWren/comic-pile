import { useMutation, useQueryClient } from '@tanstack/react-query'
import { issuesApi } from '../services/api-issues'
import { invalidateAfterReaderProgress } from '../query/cacheEffects'

/** One shared write and invalidation path for reader read/unread actions. */
export function useReaderProgress(issueId: number, isRead: boolean) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => isRead ? issuesApi.markUnread(issueId) : issuesApi.markRead(issueId),
    onSuccess: () => invalidateAfterReaderProgress(client),
  })
}
