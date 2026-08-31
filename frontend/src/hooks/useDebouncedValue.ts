import { useEffect, useState } from 'react'

/**
 * Return a debounced copy of `value` that only updates after `delayMs`
 * milliseconds of no changes. Use this to avoid firing expensive effects
 * (like network queries) on every keystroke.
 *
 * @param value - Source value that may change rapidly (e.g. keystrokes).
 * @param delayMs - Quiet period before the debounced value commits.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState<T>(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
