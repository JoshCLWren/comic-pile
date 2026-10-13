import type { components } from '../../generated/openapi'

/** One visible tag as returned on queue rows and roll bootstrap entries. */
type ThreadTag = components['schemas']['TagResponse']

const DENSITY = {
  /** Queue card rows and other comfortable list surfaces. */
  row: {
    dot: 'h-2.5 w-2.5',
    name: 'max-w-[120px]',
    pill: 'gap-1.5 px-2.5 py-1 text-sm',
  },
  /** Roll pool sections, where rows are already dense metadata. */
  compact: {
    dot: 'h-2 w-2',
    name: 'max-w-[100px]',
    pill: 'gap-1 px-2 py-0.5 text-[11px]',
  },
} as const

export interface ThreadTagRowProps {
  /** Visible tags for one thread. Omitted or empty renders nothing. */
  tags?: ThreadTag[]
  /** Accessible name describing whose tags these are, e.g. `Tags for Spider-Man`. */
  label: string
  /** Row context. Defaults to `row`; the Roll surfaces pass `compact`. */
  density?: keyof typeof DENSITY
  /** Layout placement for the wrapping list, e.g. `mt-1` or `shrink-0`. */
  className?: string
}

/**
 * Read-only tag pills for surfaces that already carry tags inline
 * (issue #3425).
 *
 * The queue row and every Roll pool section need the same at-a-glance tag
 * signal, so the treatment lives here once instead of being re-invented per
 * call site. Each pill carries the tag's identity only — identity color dot
 * plus name, bold in the primary text color on the panel background — which
 * matches the canonical chip treatment in `TagChips` and keeps tags quieter
 * than the row's primary actions. Editing stays on the thread's own tag
 * section; this row is a signal, not a control.
 *
 * Pills wrap rather than overflow, and names truncate so a long tag can never
 * push the row's title or actions out of its container. When a thread has no
 * visible tags the row renders nothing, so optional content leaves no
 * geometry behind.
 */
export function ThreadTagRow({ tags, label, density = 'row', className = '' }: ThreadTagRowProps) {
  if (!tags || tags.length === 0) return null
  const scale = DENSITY[density]

  return (
    <ul
      aria-label={label}
      className={`flex min-w-0 max-w-full flex-wrap gap-1 ${className}`}
    >
      {tags.map((tag) => (
        <li key={tag.id} className="min-w-0 max-w-full">
          <span
            className={`inline-flex max-w-full items-center rounded-full border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] font-bold text-[var(--theme-text-primary)] ${scale.pill}`}
          >
            <span
              aria-hidden="true"
              title={tag.name}
              className={`${scale.dot} shrink-0 rounded-full`}
              style={{ backgroundColor: tag.color }}
            />
            <span className={`min-w-0 truncate ${scale.name}`}>{tag.name}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}
