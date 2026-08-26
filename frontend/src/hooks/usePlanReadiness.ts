import { useCallback, useEffect, useState } from 'react'
import {
  continuityPlansApi,
  type ContinuityPlanReadinessResponse,
} from '../services/api-continuity-plans'

interface PlanReadinessState {
  readiness: ContinuityPlanReadinessResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: PlanReadinessState = {
  readiness: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function usePlanReadiness(
  planId: number | null | undefined,
  refreshKey = 0,
): PlanReadinessState {
  const [state, setState] = useState(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)
  const refetch = useCallback(() => setAttempt((value) => value + 1), [])

  useEffect(() => {
    if (planId == null || !Number.isInteger(planId) || planId <= 0) {
      setState({ ...EMPTY_STATE, refetch })
      return
    }

    let isCurrent = true
    setState((current) => ({ ...current, isLoading: true, error: null }))

    continuityPlansApi
      .readiness(planId)
      .then((readiness) => {
        if (isCurrent) {
          setState({ readiness, isLoading: false, error: null, refetch })
        }
      })
      .catch((reason: unknown) => {
        if (isCurrent) {
          const error =
            reason instanceof Error ? reason : new Error('Unable to load plan readiness')
          setState({ readiness: null, isLoading: false, error, refetch })
        }
      })

    return () => {
      isCurrent = false
    }
  }, [attempt, planId, refetch, refreshKey])

  useEffect(() => {
    if (planId == null) return
    const onVisible = () => {
      if (document.visibilityState === 'visible') refetch()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [planId, refetch])

  return state
}
