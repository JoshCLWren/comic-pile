import { useCallback, useEffect, useState } from 'react'
import { readerContextApi } from '../services/api'
import type { ReaderContextResponse } from '../types'

interface ReaderContextState {
  data: ReaderContextResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ReaderContextState = {
  data: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useReaderContext(
  issueId: number | null | undefined,
): ReaderContextState {
  const [state, setState] = useState<ReaderContextState>(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)

  const refetch = useCallback(() => {
    setAttempt((prev) => prev + 1)
  }, [])

  useEffect(() => {
    if (issueId == null) {
      setState({ ...EMPTY_STATE, refetch })
      return
    }

    let isCurrent = true
    setState({ data: null, isLoading: true, error: null, refetch })

    readerContextApi.get(issueId).then(
      (data) => {
        if (isCurrent) {
          setState({ data, isLoading: false, error: null, refetch })
        }
      },
      (reason: unknown) => {
        if (isCurrent) {
          const error = reason instanceof Error ? reason : new Error(
            'Unable to load reader context',
          )
          setState({ data: null, isLoading: false, error, refetch })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [attempt, issueId, refetch])

  return state
}