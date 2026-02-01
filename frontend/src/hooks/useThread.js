import { useState, useEffect, useCallback } from 'react'
import { threadsApi } from '../services/api'

export function useThreads() {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)

  const fetchData = useCallback(async () => {
    setIsPending(true)
    setIsError(false)
    try {
      const result = await threadsApi.list()
      setData(result)
    } catch {
      setIsError(true)
    } finally {
      setIsPending(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { data, isPending, isError, refetch: fetchData }
}

export function useThread(id) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    if (!id) {
      setData(null)
      setIsError(false)
      setIsPending(false)
      return
    }

    let isMounted = true

    const fetchData = async () => {
      setIsPending(true)
      setIsError(false)
      try {
        const result = await threadsApi.get(id)
        if (isMounted) {
          setData(result)
        }
      } catch {
        if (isMounted) {
          setIsError(true)
        }
      } finally {
        if (isMounted) {
          setIsPending(false)
        }
      }
    }

    fetchData()

    return () => {
      isMounted = false
    }
  }, [id])

  return { data, isPending, isError }
}

export function useStaleThreads(days = 30) {
  const [data, setData] = useState(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)

  useEffect(() => {
    let isMounted = true

    const fetchData = async () => {
      setIsPending(true)
      setIsError(false)
      try {
        const result = await threadsApi.listStale(days)
        if (isMounted) {
          setData(result)
        }
      } catch {
        if (isMounted) {
          setIsError(true)
        }
      } finally {
        if (isMounted) {
          setIsPending(false)
        }
      }
    }

    fetchData()

    return () => {
      isMounted = false
    }
  }, [days])

  return { data, isPending, isError }
}

export function useCreateThread() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (data) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.create(data)
    } catch (error) {
      console.error('Failed to create thread:', error.response?.data?.detail || error.message)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useUpdateThread() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async ({ id, data }) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.update(id, data)
    } catch (error) {
      console.error('Failed to update thread:', error.response?.data?.detail || error.message)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useDeleteThread() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (id) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.delete(id)
    } catch (error) {
      console.error('Failed to delete thread:', error.response?.data?.detail || error.message)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}

export function useReactivateThread() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = useCallback(async (data) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.reactivate(data)
    } catch (error) {
      console.error('Failed to reactivate thread:', error.response?.data?.detail || error.message)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
