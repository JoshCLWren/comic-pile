import { useEffect, useMemo, useState } from 'react'
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'

interface CrossoverGroupsState {
  groupsByThreadId: Record<number, DependencyGroupSummary[]>
  isPending: boolean
  error: Error | null
}

const EMPTY_GROUPS: Record<number, DependencyGroupSummary[]> = {}
const MAX_THREAD_IDS_PER_REQUEST = 200

function chunkThreadIds(threadIds: number[]): number[][] {
  const chunks: number[][] = []
  for (let index = 0; index < threadIds.length; index += MAX_THREAD_IDS_PER_REQUEST) {
    chunks.push(threadIds.slice(index, index + MAX_THREAD_IDS_PER_REQUEST))
  }
  return chunks
}

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  const requestKey = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b).join(','),
    [threadIds],
  )
  const [state, setState] = useState<CrossoverGroupsState>({
    groupsByThreadId: EMPTY_GROUPS,
    isPending: requestKey.length > 0,
    error: null,
  })

  useEffect(() => {
    let cancelled = false
    const requestedThreadIds = requestKey
      ? requestKey.split(',').map((threadId) => Number(threadId))
      : []

    if (requestedThreadIds.length === 0) {
      setState({ groupsByThreadId: EMPTY_GROUPS, isPending: false, error: null })
      return () => {
        cancelled = true
      }
    }

    setState((current) => ({ ...current, isPending: true, error: null }))

    Promise.all(
      chunkThreadIds(requestedThreadIds).map((threadIdChunk) =>
        dependencyGroupsApi.listForThreads(threadIdChunk),
      ),
    )
      .then((responses) => {
        if (cancelled) return
        const groupsByThreadId = Object.assign({}, ...responses)
        setState({ groupsByThreadId, isPending: false, error: null })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        setState({
          groupsByThreadId: EMPTY_GROUPS,
          isPending: false,
          error: error instanceof Error ? error : new Error('Failed to load crossovers'),
        })
      })

    return () => {
      cancelled = true
    }
  }, [requestKey])

  return state
}
