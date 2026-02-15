import { useState, useEffect, useCallback } from 'react'
import { threadsApi } from '../services/api'

interface Thread {
  id: number
  title: string
  format: string
  issues_remaining: number
  notes?: string
  queue_position?: number
  last_rating?: number
  is_pending?: boolean
}

interface CreateThreadData {
  title: string
  format: string
  issues_remaining: number
  notes?: string
}

interface UpdateThreadData extends Partial<CreateThreadData> {}

interface UpdateThreadParams {
  id: number
  data: UpdateThreadData
}

interface ReactivateThreadData {
  thread_id: number
}

export function useThreads() {
  const [data, setData] = useState<Thread[] | null>(null)
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

export function useThread(id: number | null | undefined) {
  const [data, setData] = useState<Thread | null>(null)
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
  const [data, setData] = useState<Thread[] | null>(null)
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

  const mutate = useCallback(async (data: CreateThreadData) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.create(data)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to create thread:', err.response?.data?.detail || err.message)
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

  const mutate = useCallback(async ({ id, data }: UpdateThreadParams) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.update(id, data)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to update thread:', err.response?.data?.detail || err.message)
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

  const mutate = useCallback(async (id: number) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.delete(id)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to delete thread:', err.response?.data?.detail || err.message)
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

  const mutate = useCallback(async (data: ReactivateThreadData) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.reactivate(data)
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } }; message?: string }
      console.error('Failed to reactivate thread:', err.response?.data?.detail || err.message)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
