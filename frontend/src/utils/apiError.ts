import axios from 'axios'
import { isNonNullObject, hasProperty, isString } from './runtimeChecks'

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
    // SAFETY: isNonNullObject and hasProperty(response) above guarantee the optional response read is safe.
    return (error as ApiLikeError).response?.status ?? null
  }
  return null
}

/** Server responses at or above this status do not prove the request was not applied. */
const INDETERMINATE_STATUS_FLOOR = 500

/**
 * Whether an API failure leaves the operation's outcome unknown.
 *
 * A 4xx response is a definitive refusal: the server rejected the request without applying
 * it, so "nothing changed" is truthful. A 5xx, or a transport failure that never produced a
 * response (offline, timeout), may have applied the request before the response was lost, so
 * callers must not assert the operation had no effect. Retrying such a request is safe when
 * the endpoint is idempotent.
 */
export function isIndeterminateApiOutcome(error: unknown): boolean {
  const status = getApiErrorStatus(error)
  if (status !== null) {
    return status >= INDETERMINATE_STATUS_FLOOR
  }
  return isTransportFailure(error)
}

/** Whether the failure is a transport error that never received an HTTP response. */
function isTransportFailure(error: unknown): boolean {
  if (axios.isAxiosError(error)) {
    // axios throws without a response for a timeout, an aborted request, or an offline client.
    return error.response === undefined || error.response === null
  }
  if (error instanceof Error) {
    return isGenericNetworkError(error.message)
  }
  if (isNonNullObject(error) && hasProperty(error, 'message')) {
    return isString(error.message) && isGenericNetworkError(error.message)
  }
  return false
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
    // SAFETY: isNonNullObject and hasProperty(response) above guarantee reading response.data.detail is safe.
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
