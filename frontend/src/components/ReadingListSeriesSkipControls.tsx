import { useId, useMemo } from 'react'
import type { CustomCBLEntry } from '../services/api-custom-cbl'
import TriStateCheckbox from './TriStateCheckbox'

interface Props {
  /** Every entry currently in the saved Reading List draft. */
  entries: CustomCBLEntry[]
  /** Disable both series and per-issue controls while a write is in flight. */
  disabled: boolean
  /** Apply one skip/restore choice to every entry in a series. */
  onSeriesSkipChange: (threadId: number, skipped: boolean) => void
}

interface SeriesSkipGroup {
  /** Durable series identity; same-named volumes stay separate. */
  threadId: number
  seriesName: string
  entryCount: number
  skippedCount: number
}

/**
 * Group the saved-list draft by series for one tri-state skip control per volume.
 *
 * Reader order stays untouched: the ordered issue list remains authoritative,
 * and a series choice only writes the existing per-issue skip intent.
 *
 * @param entries - Every entry currently in the draft.
 * @returns One group per series in first-appearance order.
 */
function groupBySeries(entries: CustomCBLEntry[]): SeriesSkipGroup[] {
  const groups = new Map<number, CustomCBLEntry[]>()
  for (const entry of entries) {
    const existing = groups.get(entry.thread_id)
    if (existing) existing.push(entry)
    else groups.set(entry.thread_id, [entry])
  }
  return Array.from(groups.entries()).map(([threadId, seriesEntries]) => ({
    threadId,
    seriesName: seriesEntries[0]!.series_name,
    entryCount: seriesEntries.length,
    skippedCount: seriesEntries.filter((entry) => entry.skipped).length,
  }))
}

/**
 * Skip or restore every issue in one series without leaving the saved-list editor.
 *
 * The tri-state checkbox mirrors the CBL creation flow: skipping one issue shows
 * a mixed series control, and clicking that mixed control skips the rest of the
 * volume at once. Per-issue settings still override an individual entry.
 *
 * @param props - Draft entries, disabled state, and the series choice handler.
 * @returns The series-level skip controls.
 */
export default function ReadingListSeriesSkipControls({
  entries,
  disabled,
  onSeriesSkipChange,
}: Props) {
  const groups = useMemo(() => groupBySeries(entries), [entries])
  const headingId = useId()

  if (groups.length === 0) return null

  return (
    <section
      className="space-y-2 rounded-xl border border-[var(--theme-border)] p-3"
      aria-labelledby={headingId}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4
          id={headingId}
          className="text-sm font-bold text-[var(--theme-text-primary)]"
        >
          Skip or restore a whole series
        </h4>
        <span className="text-xs text-[var(--theme-text-muted)]">
          Per-issue settings below still apply.
        </span>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2">
        {groups.map((group) => (
          <li
            key={group.threadId}
            className="flex items-center justify-between gap-2 rounded-lg border border-[var(--theme-border)] p-2"
          >
            <div className="flex min-w-0 items-center gap-2">
              <TriStateCheckbox
                checked={group.skippedCount === group.entryCount}
                indeterminate={group.skippedCount > 0 && group.skippedCount < group.entryCount}
                disabled={disabled}
                label={`Skip ${group.seriesName} series in this list`}
                onChange={(skip) => onSeriesSkipChange(group.threadId, skip)}
              />
              <span className="min-w-0 truncate text-sm font-semibold text-[var(--theme-text-primary)]">
                {group.seriesName}
              </span>
            </div>
            <span className="shrink-0 text-xs text-[var(--theme-text-muted)]">
              {group.skippedCount} of {group.entryCount} skipped in this list
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
