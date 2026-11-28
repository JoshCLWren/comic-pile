import { type ActivityFilters, hasActiveActivityFilters } from '../utils/activityFilters'
import { ACTIVITY_TYPE_OPTIONS, activityLabel } from '../utils/activityLabels'

interface HistoryFiltersProps {
  /** Currently applied filter draft. */
  filters: ActivityFilters
  /** Called with the complete next filter state for each control change. */
  onChange: (next: ActivityFilters) => void
  /** Reset every filter to the unfiltered chronological stream. */
  onClear: () => void
}

/**
 * Server-driven History filters.
 *
 * Text, series, type and reader-local date controls all feed the same
 * `GET /api/v2/activity` query; the page never re-filters or re-sorts a page in
 * the browser, so the resource's causal order and cursor stay authoritative.
 * Controls use the surrounding panel/form vocabulary and keep labels visible
 * at phone widths.
 */
export default function HistoryFilters({ filters, onChange, onClear }: HistoryFiltersProps) {
  const active = hasActiveActivityFilters(filters)

  return (
    <section
      className="surface-panel rounded-xl border border-[var(--theme-border)] p-3 md:p-4 space-y-3"
      aria-label="Filter activity"
    >
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        <div className="min-w-0 space-y-1">
          <label
            htmlFor="activity-search"
            className="block text-sm font-medium text-[var(--theme-text-primary)]"
          >
            Search activity
          </label>
          <input
            id="activity-search"
            type="search"
            maxLength={200}
            value={filters.q}
            placeholder="Series, issue or action"
            onChange={(event) => onChange({ ...filters, q: event.target.value })}
            className="form-control w-full min-w-0 rounded-xl px-3 py-2.5 text-base md:text-sm"
          />
        </div>
        <div className="min-w-0 space-y-1">
          <label
            htmlFor="activity-series"
            className="block text-sm font-medium text-[var(--theme-text-primary)]"
          >
            Series
          </label>
          <input
            id="activity-series"
            type="search"
            maxLength={200}
            value={filters.series}
            placeholder="Any series"
            onChange={(event) => onChange({ ...filters, series: event.target.value })}
            className="form-control w-full min-w-0 rounded-xl px-3 py-2.5 text-base md:text-sm"
          />
        </div>
        <div className="min-w-0 space-y-1">
          <label
            htmlFor="activity-type"
            className="block text-sm font-medium text-[var(--theme-text-primary)]"
          >
            Activity type
          </label>
          <select
            id="activity-type"
            value={filters.type}
            onChange={(event) => onChange({ ...filters, type: event.target.value })}
            className="form-control w-full min-w-0 rounded-xl px-3 py-2.5 text-base md:text-sm"
          >
            <option value="">All activity types</option>
            {ACTIVITY_TYPE_OPTIONS.map((type) => (
              <option key={type} value={type}>
                {activityLabel(type)}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-0 space-y-1">
          <label
            htmlFor="activity-date-from"
            className="block text-sm font-medium text-[var(--theme-text-primary)]"
          >
            From date
          </label>
          <input
            id="activity-date-from"
            type="date"
            value={filters.dateFrom}
            onChange={(event) => onChange({ ...filters, dateFrom: event.target.value })}
            className="form-control w-full min-w-0 rounded-xl px-3 py-2.5 text-base md:text-sm"
          />
        </div>
        <div className="min-w-0 space-y-1">
          <label
            htmlFor="activity-date-to"
            className="block text-sm font-medium text-[var(--theme-text-primary)]"
          >
            To date
          </label>
          <input
            id="activity-date-to"
            type="date"
            value={filters.dateTo}
            onChange={(event) => onChange({ ...filters, dateTo: event.target.value })}
            className="form-control w-full min-w-0 rounded-xl px-3 py-2.5 text-base md:text-sm"
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-[var(--theme-text-muted)]">
          Dates use your local calendar day. Filters combine and keep History in chronological order.
        </p>
        <button
          type="button"
          onClick={onClear}
          disabled={!active}
          className="h-9 px-4 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors disabled:opacity-50"
        >
          Clear filters
        </button>
      </div>
    </section>
  )
}
