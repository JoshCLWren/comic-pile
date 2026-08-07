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

export function useCrossoverGroups(threadIds: number[]): CrossoverGroupsState {
  const uniqueThreadIds = useMemo(
    () => [...new Set(threadIds)].sort((a, b) => a - b),
    [threadIds],
  )
  const requestKey = uniqueThreadIds.join(',')
  const [state, setState] = useState<CrossoverGroupsState>({
    groupsByThreadId: EMPTY_GROUPS,
    isPending: uniqueThreadIds.length > 0,
    error: null,
  })

  useEffect(() => {
    let cancelled = false

    if (uniqueThreadIds.length === 0) {
      setState({ groupsByThreadId: EMPTY_GROUPS, isPending: false, error: null })
      return () => {
        cancelled = true
      }
    }

    setState((current) => ({ ...current, isPending: true, error: null }))

    dependencyGroupsApi.listForThreads(uniqueThreadIds)
      .then((groupsByThreadId) => {
        if (cancelled) return
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
