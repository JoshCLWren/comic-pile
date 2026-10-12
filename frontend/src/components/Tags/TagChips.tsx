import { useState } from 'react'
import { Link } from 'react-router-dom'
import type {
  EffectiveTag,
  EffectiveTagsResponse,
  InheritanceSource,
  Tag,
} from '../../services/api-tags'

/**
 * Destination route for an inheritance source (issue #3032).
 *
 * Threads and Reading Plans have stable detail routes. Issue-typed sources in
 * v1 are always the queried object itself (issues inherit from threads and
 * plans, never from other issues), so they render as text rather than a link.
 */
export function sourceRoute(source: InheritanceSource): string | null {
  if (source.target_type === 'Thread') return `/thread/${source.target_id}`
  if (source.target_type === 'ContinuityPlan')
    return `/continuity-plans/${source.target_id}`
  return null
}

function ColorDot({ color, label }: { color: string; label: string }) {
  return (
    <span
      aria-hidden="true"
      title={label}
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
    />
  )
}

function SourcesList({ tagName, sources }: { tagName: string; sources: InheritanceSource[] }) {
  return (
    <ul className="mt-1 flex flex-wrap gap-1 pl-2" aria-label={`Sources for ${tagName}`}>
      {sources.map((source) => {
        const route = sourceRoute(source)
        const label = `${source.target_type} ${source.display_name}`
        return (
          <li key={`${source.target_type}:${source.target_id}`}>
            {route ? (
              <Link
                to={route}
                className="block max-w-full truncate rounded-lg border border-[var(--theme-border)] px-2 py-0.5 text-[11px] font-semibold text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
                title={`Open ${label}`}
              >
                {label}
              </Link>
            ) : (
              <span
                className="block max-w-full truncate rounded-lg border border-[var(--theme-border)] px-2 py-0.5 text-[11px] text-[var(--theme-text-dim)]"
                title={label}
              >
                {label}
              </span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

interface DirectChipProps {
  tag: Tag
  canEdit: boolean
  onRemove?: (tag: Tag) => void
  /** Inheritance sources beyond the queried object itself, if any. */
  extraSources?: InheritanceSource[]
}

function DirectChip({ tag, canEdit, onRemove, extraSources }: DirectChipProps) {
  const [expanded, setExpanded] = useState(false)
  const hasExtraSources = !!extraSources && extraSources.length > 0

  return (
    <li className="min-w-0 max-w-full">
      <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2.5 py-1 text-[var(--theme-text-primary)]">
        <ColorDot color={tag.color} label={tag.name} />
        <span className="min-w-0 truncate text-sm font-bold">{tag.name}</span>
        {tag.scope === 'global' && (
          <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">
            Global
          </span>
        )}
        {hasExtraSources && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Hide' : 'Show'} additional sources for tag ${tag.name}`}
            className="shrink-0 rounded-full px-1 text-[11px] font-medium text-[var(--theme-text-muted)] underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          >
            +{extraSources.length} inherited
          </button>
        )}
        {canEdit && onRemove && (
          <button
            type="button"
            onClick={() => onRemove(tag)}
            aria-label={`Remove tag ${tag.name}`}
            className="shrink-0 rounded-full px-1 text-[11px] text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-danger)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
          >
            ×
          </button>
        )}
      </span>
      {expanded && hasExtraSources && (
        <SourcesList tagName={tag.name} sources={extraSources} />
      )}
    </li>
  )
}

interface InheritedChipProps {
  entry: EffectiveTag
}

/**
 * Read-only inherited tag with every inheritance source exposed.
 * A tag inherited through several paths appears once with all of its sources
 * retained, so removing one source never misleadingly implies the tag will
 * disappear. Sources link to the object that directly holds the assignment,
 * where an authorized user can edit or remove it.
 */
function InheritedChip({ entry }: InheritedChipProps) {
  const [expanded, setExpanded] = useState(false)
  const { tag, sources } = entry

  return (
    <li className="min-w-0 max-w-full">
      <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-dashed border-[var(--theme-border)] px-2.5 py-1 text-[var(--theme-text-primary)]">
        <ColorDot color={tag.color} label={tag.name} />
        <span className="min-w-0 truncate text-sm font-bold">{tag.name}</span>
        <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-text-dim)]">
          Inherited
        </span>
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Hide' : 'Show'} sources for inherited tag ${tag.name}`}
          className="shrink-0 rounded-full px-1 text-[11px] text-[var(--theme-text-muted)] underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
        >
          via {sources.length} {sources.length === 1 ? 'source' : 'sources'}
        </button>
      </span>
      {expanded && <SourcesList tagName={tag.name} sources={sources} />}
    </li>
  )
}

export interface TagChipsProps {
  data?: EffectiveTagsResponse
  isPending?: boolean
  isError?: boolean
  /** True when the viewer may edit direct assignments on this target. */
  canEdit?: boolean
  onRemoveDirect?: (tag: Tag) => void
  /**
   * Whether the remove affordance is offered for a direct tag. Defaults to
   * true: callers pass false for tags the viewer may not mutate (e.g. global
   * tags for non-admins) so editing appears only where authorized.
   */
  canRemoveTag?: (tag: Tag) => boolean
  onRetry?: () => void
  label?: string
}

/**
 * Direct + inherited tag chips for one target (issue #3032).
 *
 * Direct tags render as solid chips; inherited tags render as dashed chips
 * with an expandable source list that navigates to each contributing object.
 * Editing affordances appear only for direct assignments when `canEdit` is
 * true — inherited tags are always read-only on the child.
 */
export function TagChips({
  data,
  isPending,
  isError,
  canEdit,
  onRemoveDirect,
  canRemoveTag,
  onRetry,
  label = 'Tags',
}: TagChipsProps) {
  // A failed load is reported before the empty state: a query that errored with
  // no cached data has not been shown to be tagless, and the viewer needs the
  // retry affordance rather than a misleading "No tags yet."
  if (isPending) {
    return (
      <section aria-label={label} className="min-w-0">
        <p className="text-xs text-[var(--theme-text-dim)]">Loading tags…</p>
      </section>
    )
  }

  if (isError) {
    return (
      <section aria-label={label} className="min-w-0">
        <p className="text-xs text-[var(--theme-text-muted)]">
          Tags could not be loaded.{' '}
          {onRetry && (
            <button
              type="button"
              onClick={onRetry}
              className="underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]"
            >
              Retry
            </button>
          )}
        </p>
      </section>
    )
  }

  if (!data) {
    return (
      <section aria-label={label} className="min-w-0">
        <p className="text-xs text-[var(--theme-text-dim)]">No tags yet.</p>
      </section>
    )
  }

  const selfKey = `${data.target_type}:${data.target_id}`
  const byTagId = new Map(data.effective_tags.map((entry) => [entry.tag.id, entry]))
  const inherited = data.effective_tags.filter((entry) => !entry.direct)

  return (
    <section aria-label={label} className="min-w-0">
      {data.effective_tags.length === 0 ? (
        <p className="text-xs text-[var(--theme-text-dim)]">No tags yet.</p>
      ) : (
        <ul className="flex max-w-full flex-wrap gap-1.5">
          {data.direct_tags.map((tag) => (
            <DirectChip
              key={tag.id}
              tag={tag}
              canEdit={!!canEdit && (canRemoveTag ? canRemoveTag(tag) : true)}
              onRemove={onRemoveDirect}
              extraSources={byTagId
                .get(tag.id)
                ?.sources.filter(
                  (source) => `${source.target_type}:${source.target_id}` !== selfKey,
                )}
            />
          ))}
          {inherited.map((entry) => (
            <InheritedChip key={entry.tag.id} entry={entry} />
          ))}
        </ul>
      )}
    </section>
  )
}
