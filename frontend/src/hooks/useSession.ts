import { useCallback, useEffect, useState } from 'react'
import { sessionApi, type Session, type SnapshotData } from '../services/api'

interface SessionListParams {
  page?: number
  per_page?: number
}

const EMPTY_PARAMS = Object.freeze({})

export function useSession() {
  const [data, setData] = useState<Session | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const fetchSession = useCallback(async (): Promise<Session | null> => {
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.getCurrent()
      setData(result)
      return result
    } catch (err) {
      setIsError(true)
      setError(err as Error)
      return null
    } finally {
      setIsPending(false)
    }
  }, [])

  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  return { data, isPending, isError, error, refetch: fetchSession }
}

export function useSessions(params: SessionListParams = EMPTY_PARAMS) {
  const [data, setData] = useState<Session[] | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const effectiveParams = params ?? EMPTY_PARAMS

  const fetchSessions = useCallback(async () => {
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.list(effectiveParams)
      setData(result)
    } catch (err) {
      setIsError(true)
      setError(err as Error)
    } finally {
      setIsPending(false)
    }
  }, [effectiveParams])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  return { data, isPending, isError, error, refetch: fetchSessions }
}

export function useSessionDetails(id: number | null | undefined) {
  const [data, setData] = useState<import('../services/api').SessionDetails | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const fetchDetails = useCallback(async () => {
    if (!id) {
      setData(null)
      setIsError(false)
      setError(null)
      setIsPending(false)
      return
    }
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.getDetails(id)
      setData(result)
    } catch (err) {
      setIsError(true)
      setError(err as Error)
    } finally {
      setIsPending(false)
    }
  }, [id])

  useEffect(() => {
    fetchDetails()
  }, [fetchDetails])

  return { data, isPending, isError, error, refetch: fetchDetails }
}

export function useSessionSnapshots(id: number | null | undefined) {
  const [data, setData] = useState<SnapshotData[] | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const fetchSnapshots = useCallback(async () => {
    if (!id) {
      setData(null)
      setIsError(false)
      setError(null)
      setIsPending(false)
      return
    }
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.getSnapshots(id)
      setData(result)
    } catch (err) {
      setIsError(true)
      setError(err as Error)
    } finally {
      setIsPending(false)
    }
  }, [id])

  useEffect(() => {
    fetchSnapshots()
  }, [fetchSnapshots])

  return { data, isPending, isError, error, refetch: fetchSnapshots }
}

export function useRestoreSessionStart() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  const mutate = useCallback(async (sessionId: number) => {
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.restoreSessionStart(sessionId)
      return result
    } catch (err) {
      setIsError(true)
      setError(err as Error)
      const error = err as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to restore session:', error.response?.data?.detail || error.message)
      throw err
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError, error }
}
