import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { snoozeApi } from '../services/api'

export function useSnooze() {
  const navigate = useNavigate()
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await snoozeApi.snooze()
      navigate('/')
    } catch {
      setIsError(true)
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
    } catch {
      setIsError(true)
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
