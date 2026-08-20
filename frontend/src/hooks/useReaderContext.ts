import { useCallback, useEffect, useRef, useState } from 'react'
import {
  readerContextApi,
  type ReaderContextResponse,
} from '../services/api-reader-context'

interface ReaderContextState {
  context: ReaderContextResponse | null
  isLoading: boolean
  error: Error | null
  refetch: () => void
}

const EMPTY_STATE: ReaderContextState = {
  context: null,
  isLoading: false,
  error: null,
  refetch: () => undefined,
}

export function useReaderContext(
  issueId: number | null | undefined,
): ReaderContextState {
  const [state, setState] = useState(EMPTY_STATE)
  const [attempt, setAttempt] = useState(0)
  const refetch = useCallback(() => setAttempt((value) => value + 1), [])
  const issueIdRef = useRef(issueId)

  useEffect(() => {
    issueIdRef.current = issueId
  }, [issueId])

  useEffect(() => {
    if (issueId == null) {
      setState({ ...EMPTY_STATE, refetch })
      return
    }

    let isCurrent = true
    setState({ context: null, isLoading: true, error: null, refetch })

    readerContextApi.get(issueId).then(
      (context) => {
        if (isCurrent && issueIdRef.current === issueId) {
          setState({ context, isLoading: false, error: null, refetch })
        }
      },
      (reason: unknown) => {
        if (isCurrent && issueIdRef.current === issueId) {
          const error =
            reason instanceof Error
              ? reason
              : new Error('Unable to load reader context')
          setState({ context: null, isLoading: false, error, refetch })
        }
      },
    )

    return () => {
      isCurrent = false
    }
  }, [attempt, issueId, refetch])

  return state
}
