import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { issuesApi } from '../services/api-issues'
import { queryKeys } from '../query/queryKeys'
import type { ManualCreatorCredit } from '../types'

interface ThreadIssueCreatorsState {
  /** Stored ComicVine credits keyed by issue id; issues without stored credits are absent. */
  creatorsByIssueId: Map<number, ManualCreatorCredit[]>
  isPending: boolean
  isError: boolean
  refetch: () => void
}

/**
 * Bulk read of stored ComicVine creator credits for a thread's issues (#3461).
 *
 * One request covers every issue row, so expanding a full issue page never
 * fans out into one provider-intelligence request per row. The read is pure
 * stored data: it does not trigger per-issue metadata refreshes. Callers use
 * the map as the preferred per-issue credits and fall back to the series'
 * manual creator credits for absent issues.
 *
 * @param threadId - Thread whose issue credits are read, or null when disabled
 * @param enabled - Gates the query (used by collapsed issue sections)
 * @returns The credits map plus query state conveniences
 */
export function useThreadIssueCreators(
  threadId: number | null,
  enabled = true,
): ThreadIssueCreatorsState {
  const query = useQuery({
    queryKey: threadId ? queryKeys.thread.issueCreators(threadId) : [],
    queryFn: () => issuesApi.listCreators(threadId!),
    enabled: !!threadId && enabled,
  })

  const creatorsByIssueId = useMemo(() => {
    const map = new Map<number, ManualCreatorCredit[]>()
    for (const entry of query.data?.issues ?? []) {
      map.set(entry.issue_id, entry.creators)
    }
    return map
  }, [query.data])

  return {
    creatorsByIssueId,
    isPending: query.isPending,
    isError: query.isError,
    refetch: () => {
      void query.refetch()
    },
  }
}
