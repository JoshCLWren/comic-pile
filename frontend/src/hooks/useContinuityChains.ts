import { useCallback, useEffect, useState } from 'react'
import {
  continuityReadinessApi,
  type ContinuityChainResponse,
} from '../services/api-continuity-readiness'

interface ContinuityChainsState {
  chains: ContinuityChainResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ContinuityChainsState = {
  chains: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useContinuityChains(
  issueId: number | null | undefined,
): ContinuityChainsState {
  const [state, setState] = useState(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)
  const refetch = useCallback(() => setAttempt((value) => value + 1), [])

  useEffect(() => {
    if (issueId == null) {
      setState({ ...EMPTY_STATE, refetch })
      return
    }

    let isCurrent = true
    setState({ chains: null, isLoading: true, error: null, refetch })

    continuityReadinessApi.resolveChains('issue', issueId).then(
      (chains) => {
        if (isCurrent) {
          setState({ chains, isLoading: false, error: null, refetch })
        }
      },
      (reason: unknown) => {
        if (isCurrent) {
          const error = reason instanceof Error ? reason : new Error('Unable to load chain')
          setState({ chains: null, isLoading: false, error, refetch })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [attempt, issueId, refetch])

  return state
}
