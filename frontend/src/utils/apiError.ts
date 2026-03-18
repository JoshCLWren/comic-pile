import axios from 'axios'

export type ApiErrorPayload = { detail?: string }
export type ApiLikeError = { response?: { status?: number; data?: ApiErrorPayload } }

export function getApiErrorStatus(error: unknown): number | null {
  if (axios.isAxiosError(error)) {
    return error.response?.status ?? null
  }
  if (error && typeof error === 'object' && 'response' in error) {
    return (error as ApiLikeError).response?.status ?? null
  }
  return null
}

export function getApiErrorDetail(error: unknown): string {
  if (axios.isAxiosError<ApiErrorPayload>(error)) {
    return error.response?.data?.detail ?? error.message ?? 'Unknown error'
  }
  if (error && typeof error === 'object' && 'response' in error) {
    return (error as ApiLikeError).response?.data?.detail ?? 'Unknown error'
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Unknown error'
}
