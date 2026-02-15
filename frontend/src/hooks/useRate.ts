import { useState } from 'react'
import { rateApi, type RateData } from '../services/api'

export function useRate() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (data: RateData) => {
    setIsPending(true)
    setIsError(false)
    try {
      await rateApi.rate(data)
    } catch (error) {
      setIsError(true)
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
