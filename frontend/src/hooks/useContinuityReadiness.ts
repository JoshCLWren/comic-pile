import { useEffect, useState } from 'react'
import {
  continuityReadinessApi,
  type ContinuityReadinessResponse,
} from '../services/api-continuity-readiness'

interface ContinuityReadinessState {
  readiness: ContinuityReadinessResponse | null
  isLoading: boolean
  error: Error | null
}

const EMPTY_STATE: ContinuityReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
}

export function useContinuityReadiness(
  issueId: number | null | undefined,
): ContinuityReadinessState {
  const [state, setState] = useState<ContinuityReadinessState>(EMPTY_STATE)

  useEffect(() => {
    if (issueId == null) {
      setState(EMPTY_STATE)
      return
    }

    let isCurrent = true
    setState({ readiness: null, isLoading: true, error: null })

    continuityReadinessApi.get('issue', issueId).then(
      (readiness) => {
        if (isCurrent) {
          setState({ readiness, isLoading: false, error: null })
        }
      },
      (reason: unknown) => {
        if (isCurrent) {
          const error = reason instanceof Error ? reason : new Error('Unable to load readiness')
          setState({ readiness: null, isLoading: false, error })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [issueId])

  return state
}
