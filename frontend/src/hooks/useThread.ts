import { useState, useEffect, useCallback, useMemo } from 'react'
import axios from 'axios'
import { useCache } from '../contexts/CacheContext'
import { threadsApi } from '../services/api'
import type { ReactivateThreadPayload, Thread, ThreadCreatePayload, ThreadQueryParams, ThreadUpdatePayload } from '../types'

export function useThreads(searchTerm = '', collectionId: number | null = null) {
  const [data, setData] = useState<Thread[] | null>(null)
  const [isPending, setIsPending] = useState(true)
  const [isError, setIsError] = useState(false)

  const { getCache, setCache } = useCache()

  const cacheKey = useMemo(() => {
    return `threads-${searchTerm}-${collectionId}`
  }, [searchTerm, collectionId])

  useEffect(() => {
    let cancelled = false

    // Check cache first: if we have cached data that hasn't expired and matches current params, use it
    const cached = getCache(cacheKey)
    if (cached) {
      const { data, timestamp } = cached
      const now = Date.now()
      // Consider cache valid for 30 seconds
      if (now - timestamp < 30000) {
        if (!cancelled) {
          setData(data)
          setIsPending(false)
        }
        return
      }
    }

    const fetchData = async () => {
      setIsPending(true)
      setIsError(false)
      try {
        const params: ThreadQueryParams = {}
        if (searchTerm?.trim()) {
          params.search = searchTerm.trim()
        }
        if (collectionId !== null) {
          params.collection_id = collectionId
        }
        // Fetch all pages transparently
        let allThreads: Thread[] = []
        let nextPageToken: string | undefined = undefined
        let pageCount = 0
        const maxPages = 100 // Safety limit

        do {
          const response = await threadsApi.list(
            Object.keys(params).length > 0 ? params : undefined,
            nextPageToken
          )
          pageCount++
          allThreads = [...allThreads, ...response.threads]
          nextPageToken = response.next_page_token
        } while (nextPageToken && pageCount < maxPages)

        // Cache the result
        setCache(cacheKey, allThreads, Date.now())

        if (!cancelled) {
          setData(allThreads)
        }
      } catch {
        if (!cancelled) {
          setIsError(true)
        }
      } finally {
        if (!cancelled) {
          setIsPending(false)
        }
      }
    }

    fetchData()

    return () => {
      cancelled = true
    }
  }, [searchTerm, collectionId, cacheKey, getCache, setCache])

  const refetch = useCallback(async () => {
    let cancelled = false
    setIsPending(true)
    setIsError(false)
    try {
      const cached = getCache(cacheKey)
      if (cached) {
        const { data, timestamp } = cached
        const now = Date.now()
        if (now - timestamp < 30000) {
          if (!cancelled) {
            setData(data)
            setIsPending(false)
          }
          return
        }
      }

      const params: ThreadQueryParams = {}
      if (searchTerm?.trim()) {
        params.search = searchTerm.trim()
      }
      if (collectionId !== null) {
        params.collection_id = collectionId
      }
      let allThreads: Thread[] = []
      let nextPageToken: string | undefined = undefined
      let pageCount = 0
      do {
        const response = await threadsApi.list(
          Object.keys(params).length > 0 ? params : undefined,
          nextPageToken
        )
        pageCount++
        allThreads = [...allThreads, ...response.threads]
        nextPageToken = response.next_page_token
      } while (nextPageToken && pageCount < 100)

      setCache(cacheKey, allThreads, Date.now())

      if (!cancelled) {
        setData(allThreads)
      }
    } catch {
      if (!cancelled) {
        setIsError(true)
      }
    } finally {
      if (!cancelled) {
        setIsPending(false)
      }
    }
  }, [searchTerm, collectionId, cacheKey, getCache, setCache])

  return { data, isPending, isError, refetch }
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

  const mutate = useCallback(async (data: ThreadCreatePayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.create(data)
    } catch (error: unknown) {
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail || error.message
        : error instanceof Error
          ? error.message
          : 'Unknown error'
      console.error('Failed to create thread:', detail)
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

  const mutate = useCallback(async ({ id, data }: { id: number; data: ThreadUpdatePayload }) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.update(id, data)
    } catch (error: unknown) {
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail || error.message
        : error instanceof Error
          ? error.message
          : 'Unknown error'
      console.error('Failed to update thread:', detail)
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
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail || error.message
        : error instanceof Error
          ? error.message
          : 'Unknown error'
      console.error('Failed to delete thread:', detail)
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

  const mutate = useCallback(async (data: ReactivateThreadPayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      return await threadsApi.reactivate(data)
    } catch (error: unknown) {
      const detail = axios.isAxiosError<{ detail?: string }>(error)
        ? error.response?.data?.detail || error.message
        : error instanceof Error
          ? error.message
          : 'Unknown error'
      console.error('Failed to reactivate thread:', detail)
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }, [])

  return { mutate, isPending, isError }
}
