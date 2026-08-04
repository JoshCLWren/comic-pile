import { useRef, useState } from 'react'
import { rateApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { RatePayload } from '../types'

export function useRate() {
  const [isPending, setIsPending] = useState(false)
  const [isError, setIsError] = useState(false)
  const inFlightRequest = useRef<ReturnType<typeof rateApi.rate> | null>(null)

  const mutate = async (data: RatePayload) => {
    if (inFlightRequest.current) return inFlightRequest.current

    setIsPending(true)
    setIsError(false)
    const request = rateApi.rate(data)
    inFlightRequest.current = request

    try {
      return await request
    } catch (error: unknown) {
      setIsError(true)
      console.error('Failed to rate thread:', getApiErrorDetail(error))
      throw error
    } finally {
      if (inFlightRequest.current === request) {
        inFlightRequest.current = null
        setIsPending(false)
      }
    }
  }

  return { mutate, isPending, isError }
}
