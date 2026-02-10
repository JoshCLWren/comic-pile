import { useCallback, useEffect, useState } from 'react'
import { sessionApi } from '../services/api'

const EMPTY_PARAMS = Object.freeze({})

export function useSession() {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState(null)

  const fetchSession = useCallback(async () => {
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.getCurrent()
      setData(result)
    } catch (err) {
      setIsError(true)
      setError(err)
    } finally {
      setIsPending(false)
    }
  }, [])

  useEffect(() => {
    fetchSession()
  }, [fetchSession])

  return { data, setData, isPending, isError, error, refetch: fetchSession }
}

export function useSessions(params = EMPTY_PARAMS) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState(null)

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
      setError(err)
    } finally {
      setIsPending(false)
    }
  }, [effectiveParams])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  return { data, isPending, isError, error, refetch: fetchSessions }
}

export function useSessionDetails(id) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState(null)

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
      setError(err)
    } finally {
      setIsPending(false)
    }
  }, [id])

  useEffect(() => {
    fetchDetails()
  }, [fetchDetails])

  return { data, isPending, isError, error, refetch: fetchDetails }
}

export function useSessionSnapshots(id) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)
  const [error, setError] = useState(null)

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
      setError(err)
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
  const [error, setError] = useState(null)

  const mutate = useCallback(async (sessionId) => {
    setIsPending(true)
    setIsError(false)
    setError(null)
    try {
      const result = await sessionApi.restoreSessionStart(sessionId)
      return result
    } catch (err) {
      setIsError(true)
      setError(err)
      console.error('Failed to restore session:', err.response?.data?.detail || err.message)
      throw err
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError, error }
}
