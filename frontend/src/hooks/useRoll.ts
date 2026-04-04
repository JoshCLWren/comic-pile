import { useState } from 'react'
import { rollApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { OverrideRollPayload } from '../types'

export function useRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await rollApi.roll()
      setIsPending(false)
      return response
    } catch (error: unknown) {
      setIsPending(false)
      setIsError(true)
      console.error('Failed to roll:', getApiErrorDetail(error))
      throw error
    }
  }

  return { mutate, isPending, isError }
}

export function useOverrideRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (data: OverrideRollPayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await rollApi.override(data)
      return response
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to override roll:', getApiErrorDetail(error))
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
      await rollApi.dismissPending()
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to dismiss pending roll:', getApiErrorDetail(error))
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
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to set die:', getApiErrorDetail(error))
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
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to clear manual die:', getApiErrorDetail(error))
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
      await rollApi.reroll()
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to reroll:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}
