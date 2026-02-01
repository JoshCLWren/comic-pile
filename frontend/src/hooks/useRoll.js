import { useState } from 'react'
import { rollApi } from '../services/api'

export function useRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async () => {
    setIsPending(true)
    setIsError(false)
    try {
      const response = await rollApi.roll()
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

export function useOverrideRoll() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (data) => {
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
      await rollApi.dismissPending()
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
  
  const mutate = async (die) => {
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
      await rollApi.reroll()
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }
  
  return { mutate, isPending, isError }
}
