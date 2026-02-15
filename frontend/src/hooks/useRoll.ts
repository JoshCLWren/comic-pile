import { useState } from 'react'
import { rollApi } from '../services/api'

interface RollResponse {
  title: string
  format: string
  issues_remaining: number
  thread_id: number
  queue_position: number
  is_pending: boolean
}

export function useRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (): Promise<RollResponse> => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await rollApi.roll()
      setIsPending(false)
      return response
    } catch (error) {
      setIsPending(false)
      setIsError(true)
      throw error
    }
  }

  return { mutate, isPending, isError }
}

export function useOverrideRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (data: { thread_id: number }): Promise<RollResponse> => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await rollApi.override(data)
      return response
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}

export function useDismissPending() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  
  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await rollApi.dismissPending?.()
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}

export function useSetDie() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  
  const mutate = async (die: number) => {
    setIsPending(true)
    setIsError(false)
    try {
      await rollApi.setDie(die)
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}

export function useClearManualDie() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  
  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await rollApi.clearManualDie()
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}

export function useReroll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  
  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      await rollApi.reroll?.()
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}
