import { useEffect, useState } from 'react'
import {
  dependencyGroupsApi,
  type DependencyGroupSummary,
} from '../services/api-dependency-groups'

interface DependencyGroupsState {
  groups: DependencyGroupSummary[]
  isLoading: boolean
  error: Error | null
}

const EMPTY_STATE: DependencyGroupsState = {
  groups: [],
  isLoading: false,
  error: null,
}

export function useDependencyGroups(threadId: number | null | undefined): DependencyGroupsState {
  const [state, setState] = useState<DependencyGroupsState>(EMPTY_STATE)

  useEffect(() => {
    if (threadId == null) {
      setState(EMPTY_STATE)
      return
    }

    let isCurrent = true
    setState({ groups: [], isLoading: true, error: null })

    dependencyGroupsApi.listForThread(threadId).then(
      (groups) => {
        if (isCurrent) {
          setState({ groups, isLoading: false, error: null })
        }
      },
      (reason: unknown) => {
        if (isCurrent) {
          const error = reason instanceof Error ? reason : new Error('Unable to load reading-order groups')
          setState({ groups: [], isLoading: false, error })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [threadId])

  return state
}
