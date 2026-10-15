/**
 * The part of a tag a list-row chip needs: identity plus its display color.
 *
 * Deliberately narrower than the full {@link Tag}. The generated queue client
 * types `scope` as a plain string while the hand-written tag client narrows
 * it to a union, so a list row must accept either shape; the chip only reads
 * the three fields below.
 */
export interface ThreadTagChip {
  id: number
  name: string
  /** Hex `#RRGGBG` identity color from the fixed tag palette. */
  color: string
}

interface ThreadTagChipsProps {
  /** Visible direct tags for the thread. Omitted or empty renders nothing. */
  tags?: ThreadTagChip[]
  /** Accessible name for the chip group, e.g. `Tags for Spider-Man`. */
  label: string
  /** Extra classes for the chip group, typically spacing from the row above. */
  className?: string
}

/**
 * Read-only tag chips for one thread inside a list row (issue #3425).
 *
 * This is the dense sibling of {@link TagChips}, which owns editing and
 * inheritance-source detail on a detail page. A Queue row and a Roll die face
 * only need the tag's identity, so the pill keeps the same grammar as the
 * detail chips — color dot plus bold name in the primary text color on the
 * panel surface — at the metadata size these dense rows already use.
 *
 * Chips are plain spans: the surrounding row is the only interactive element,
 * and a nested control would either swallow the row click or open an editor
 * the list surface has no data for.
 */
export function ThreadTagChips({ tags, label, className = '' }: ThreadTagChipsProps) {
  if (!tags || tags.length === 0) return null

  const rootClass = className ? `min-w-0 ${className}` : 'min-w-0'

  return (
    <section aria-label={label} className={rootClass}>
      <ul className="flex max-w-full flex-wrap gap-1">
        {tags.map((tag) => (
          <li key={tag.id} className="min-w-0 max-w-full">
            <span
              title={tag.name}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 py-0.5 text-[11px] font-bold text-[var(--theme-text-primary)]"
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
    </section>
  )
}
