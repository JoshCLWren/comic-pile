import { useEffect, useState } from 'react'

/**
 * Debounce a rapidly changing value.
 *
 * Used by search inputs so a keystroke does not immediately become a new
 * server query; the debounced value feeds the query key, so the request only
 * settles once typing pauses.
 *
 * @param value - Value to debounce (for example a controlled search string).
 * @param delay - Quiet period in milliseconds before the value is published.
 * @returns The last value that stayed unchanged for `delay` milliseconds.
 */
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)

  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedValue(value)
    }, delay)

    return () => {
      clearTimeout(handler)
    }
  }, [value, delay])

  return debouncedValue
}
