import type { AxiosError } from 'axios'

export function tagErrorMessage(err: unknown, fallback: string): string {
  // If the error is an Axios error with a response structure, prefer the server detail
  // SAFETY: We narrow by checking for the expected AxiosError shape at the I/O boundary
  const axiosErr = err as AxiosError<{ detail?: string }> | null
  if (axiosErr?.response?.data?.detail && typeof axiosErr.response.data.detail === 'string') {
    return axiosErr.response.data.detail
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
