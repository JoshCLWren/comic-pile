import { useState } from 'react'
import { rateApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { RatePayload } from '../types'

export function useRate() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)

  const mutate = async (data: RatePayload) => {
    setIsPending(true)
    setIsError(false)
    try {
      await rateApi.rate(data)
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to rate thread:', getApiErrorDetail(error))
      throw error
    } finally {
      setIsPending(false)
    }
  }

  return { mutate, isPending, isError }
}
