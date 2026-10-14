import type { RollTagSummary } from '../../types/rollBootstrap'

export interface TagSummaryChipsProps {
  tags: RollTagSummary[]
  /**
   * Accessible name for the chip group, e.g. `Tags for Spider-Man`. Gives
   * screen-reader users the subject the tag names belong to, which the visual
   * context supplies positionally.
   */
  label: string
  /** Extra class applied to the wrapping row, for local spacing only. */
  className?: string
}

/**
 * Read-only tag chips for list rows and die faces (issue #3425).
 *
 * A tagged series used to read as untagged everywhere except its own detail
 * page, so Queue rows and Roll die faces now render the tags the server
 * already returns on those projections.
 *
 * The chip carries identity only — the tag's own palette dot plus its name —
 * in the compact `text-[11px]` metadata treatment, so tags stay scannable
 * without competing with the row's title or counts. It is deliberately
 * non-interactive: these rows are themselves click targets, and a nested
 * control inside a `role="button"` row would break keyboard activation and
 * invent a second action surface where the product has none. Tag editing stays
 * on the thread's own page.
 *
 * Optional content simply disappears: an untagged series renders nothing at
 * all rather than an empty bordered box.
 */
export function TagSummaryChips({ tags, label, className }: TagSummaryChipsProps) {
  if (tags.length === 0) return null

  return (
    <ul
      aria-label={label}
      className={`flex max-w-full flex-wrap items-center gap-1 ${className ?? ''}`.trim()}
    >
      {tags.map((tag) => (
        <li key={tag.id} className="min-w-0 max-w-full">
          <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-0.5 text-[11px] font-semibold text-[var(--theme-text-muted)]"
            title={tag.name}
          >
            <span
              aria-hidden="true"
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ backgroundColor: tag.color }}
            />
            <span className="min-w-0 truncate">{tag.name}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

export default TagSummaryChips
