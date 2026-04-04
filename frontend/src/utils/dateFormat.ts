/**
 * Date formatting utilities for consistent date/time display across the app.
 */

export type DateInput = string | Date | null | undefined

/**
 * Formats a date string or Date object to a short date format.
 */
export function formatDate(value: DateInput): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/**
 * Formats a date string or Date object to a time format.
 */
export function formatTime(value: DateInput): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

/**
 * Formats a date string or Date object to include both date and time.
 */
export function formatDateTime(value: DateInput): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return `${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  })}`
}

/**
 * Formats a date for 24-hour time display.
 */
export function formatTime24(value: DateInput): string {
  if (!value) return 'N/A'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'N/A'
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
