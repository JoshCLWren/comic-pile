import type { AxiosError } from 'axios'

export function tagErrorMessage(err: unknown, fallback: string): string {
  // If the error is an Axios error with a response structure, prefer the server detail
  if (err && typeof err === 'object' && 'response' in err) {
    const resp = (err as { response?: any }).response
    if (resp?.data?.detail && typeof resp.data.detail === 'string') {
      return resp.data.detail
    }
  }
  // If it's a plain Error, return its message
  if (err instanceof Error) {
    return err.message
  }
  // If the error is a string, return it
  if (typeof err === 'string') {
    return err
  }
  return fallback
}
