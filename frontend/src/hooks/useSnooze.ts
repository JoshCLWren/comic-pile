import { useState } from 'react'
import { snoozeApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'

export function useSnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.snooze()
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to snooze thread:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}

export function useUnsnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (threadId: number) => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.unsnooze(threadId)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to unsnooze thread:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
