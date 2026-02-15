/**
 * Date formatting utilities for consistent date/time display across the app.
 */

/**
 * Formats a date string or Date object to a short date format.
 * @param value - The date value to format
 * @returns Formatted date string (e.g., "Jan 15") or empty string if invalid
 */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (isNaN(date.getTime())) return ''
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/**
 * Formats a date string or Date object to a time format.
 * @param value - The date value to format
 * @returns Formatted time string (e.g., "2:30 PM") or empty string if invalid
 */
export function formatTime(value: string | Date | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (isNaN(date.getTime())) return ''
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
}

/**
 * Formats a date string or Date object to include both date and time.
 * @param value - The date value to format
 * @returns Formatted datetime string (e.g., "Jan 15 2:30 PM") or "—" if invalid
 */
export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (isNaN(date.getTime())) return '—'
  return `${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  })}`
}

/**
 * Formats a date for 24-hour time display.
 * @param value - The date value to format
 * @returns Formatted time string (e.g., "14:30") or "N/A" if invalid
 */
export function formatTime24(value: string | Date | null | undefined): string {
  if (!value) return 'N/A'
  const date = new Date(value)
  if (isNaN(date.getTime())) return 'N/A'
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
