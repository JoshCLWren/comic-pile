import axios from 'axios'
import { isNonNullObject, hasProperty } from './runtimeChecks'

export type ApiErrorPayload = { detail?: string }
export type ApiLikeError = { response?: { status?: number; data?: ApiErrorPayload } }

const GENERIC_NETWORK_ERRORS = ['Network Error', 'Failed to fetch', 'Network request failed']

function isGenericNetworkError(message: string): boolean {
  return GENERIC_NETWORK_ERRORS.includes(message)
}

export function getApiErrorStatus(error: unknown): number | null {
  if (axios.isAxiosError(error)) {
    return error.response?.status ?? null
  }
  if (isNonNullObject(error) && hasProperty(error, 'response')) {
    return (error as ApiLikeError).response?.status ?? null
  }
  return null
}

export function getApiErrorDetail(error: unknown): string {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    if (error.response?.data?.detail) {
      return error.response.data.detail
    }
    if (isGenericNetworkError(error.message ?? '')) {
      return 'Network error. Please check your connection.'
    }
    return error.message ?? 'Unknown error'
  }
  if (isNonNullObject(error) && hasProperty(error, 'response')) {
    return (error as ApiLikeError).response?.data?.detail ?? 'Unknown error'
  }
  if (error instanceof Error) {
    if (isGenericNetworkError(error.message)) {
      return 'Network error. Please check your connection.'
    }
    return error.message
  }
  return 'Unknown error'
}
