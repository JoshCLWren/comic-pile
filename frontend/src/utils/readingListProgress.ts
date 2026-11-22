import type { CustomCBLEntry } from '../services/api-custom-cbl'

type ProgressEntry = Pick<CustomCBLEntry, 'status' | 'skipped'>

/**
 * The editing cursor follows reading progress, not the first CBL position.
 * A skipped item isn't the next comic to read. If everything is complete,
 * keep the editor near the end of the order instead of jumping to #1.
 */
export function getReadingListProgressIndex(entries: readonly ProgressEntry[]): number {
  const nextUnreadIndex = entries.findIndex(
    (entry) => !entry.skipped && entry.status === 'unread',
  )
  if (nextUnreadIndex >= 0) return nextUnreadIndex
  return Math.max(0, entries.length - 1)
}
