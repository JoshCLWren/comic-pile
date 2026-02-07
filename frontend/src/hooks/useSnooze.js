import { useState } from 'react'
import { snoozeApi } from '../services/api'

export function useSnooze() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.snooze()
    } catch (error) {
      setIsError(true)
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

  const mutate = async (threadId) => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.unsnooze(threadId)
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
