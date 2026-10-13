import type { Tag } from '../../../services/api-tags'

export interface TagExclusionManagerProps {
  /** Active account-wide exclusions from the Roll bootstrap. */
  excludedTags: Tag[]
  /** Remove one exclusion; matching candidates become eligible immediately. */
  onRemove: (tagId: number) => void
  /** True while a removal is in flight. */
  isPending?: boolean
  /** Last load failure, when the list could not be shown. */
  loadError?: unknown | null
  onRetry?: () => void
}

/**
 * Account-wide Roll tag exclusions manager (issue #3033).
 *
 * Exclusions are persistent eligibility constraints — "do not roll anything
 * tagged X" — that stay active until removed. The manager renders only while
 * exclusions exist so an empty Roll layout never carries a decorative box;
 * the rolled issue's tag chips offer the matching "Exclude" entry point for
 * adding exclusions directly from Roll.
 */
export function TagExclusionManager({
  excludedTags,
  onRemove,
  isPending,
  loadError,
  onRetry,
}: TagExclusionManagerProps) {
  if (loadError) {
    return (
      <section
        aria-label="Excluded from Roll"
        className="surface-panel min-w-0 rounded-xl p-3 md:p-4"
      >
        <p className="text-xs text-[var(--theme-text-muted)]">
          Exclusions could not be loaded.{' '}
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

  if (excludedTags.length === 0) {
    return null
  }

  return (
    <section
      aria-label="Excluded from Roll"
      className="surface-panel min-w-0 rounded-xl p-3 md:p-4"
      data-testid="tag-exclusion-manager"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-muted)]">
          Excluded from Roll
        </span>
        <span className="text-[11px] text-[var(--theme-text-dim)]">
          Removing an exclusion makes matching series eligible again
        </span>
      </div>
      <ul className="mt-2 flex max-w-full flex-wrap gap-1.5">
        {excludedTags.map((tag) => (
          <li key={tag.id} className="min-w-0 max-w-full">
            <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2.5 py-1 text-sm font-bold text-[var(--theme-text-primary)]">
              <span
                aria-hidden="true"
                title={tag.name}
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: tag.color }}
              />
              <span className="min-w-0 truncate">{tag.name}</span>
              <button
                type="button"
                onClick={() => onRemove(tag.id)}
                disabled={isPending}
                aria-label={`Remove exclusion for tag ${tag.name}`}
                className="shrink-0 rounded-full px-1 text-[11px] text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-danger)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)] disabled:opacity-50"
              >
                ×
              </button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
