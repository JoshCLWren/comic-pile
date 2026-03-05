/**
 * Extract a human-readable error message from an API error.
 *
 * Handles Axios-style errors with response.data.detail as well as
 * plain Error objects with a message property.
 */
export function getApiErrorDetail(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail
  if (detail) return detail
  const message = (err as { message?: string })?.message
  if (message) return message
  return 'Unknown error'
}
