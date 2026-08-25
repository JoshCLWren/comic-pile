import { useCallback, useEffect, useState } from 'react'
import {
  continuityReadinessApi,
  type ContinuityReadinessResponse,
} from '../services/api-continuity-readiness'

export interface ContinuityReadinessState {
  readiness: ContinuityReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ContinuityReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export interface UseContinuityReadinessOptions {
  /** Skip fetching because a parent already shares this exact readiness state. */
  skip?: boolean
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
  options: UseContinuityReadinessOptions = {},
): ContinuityReadinessState {
  const { skip = false } = options
  const [state, setState] = useState(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)
  const refetch = useCallback(() => setAttempt((value) => value + 1), [])

  useEffect(() => {
    if (issueId == null || skip) {
      setState({ ...EMPTY_STATE, refetch })
      return
    }

    let isCurrent = true
    setState({ readiness: null, isLoading: true, error: null, refetch })

    continuityReadinessApi.evaluate('issue', issueId).then(
      (readiness) => {
        if (isCurrent) {
          setState({ readiness, isLoading: false, error: null, refetch })
        }
      },
      (reason: unknown) => {
        if (isCurrent) {
          const error = reason instanceof Error ? reason : new Error('Unable to load readiness')
          setState({ readiness: null, isLoading: false, error, refetch })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [attempt, issueId, refetch, skip])

  return state
}
