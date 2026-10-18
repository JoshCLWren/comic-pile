import { useEnableReleaseSource } from '../hooks/useReleaseSources'
import type { ReadingPlanReleaseSourceStatus } from '../services/api-continuity-plans'

function formatLastSync(lastSyncedAt: string | null): string {
  if (!lastSyncedAt) return 'Never synced'
  const date = new Date(lastSyncedAt)
  if (Number.isNaN(date.getTime())) return 'Never synced'
  return date.toLocaleString()
}

function volumeLabel(source: ReadingPlanReleaseSourceStatus): string {
  const title = source.provider_title?.trim() || source.provider_volume_id
  const meta = [
    source.provider_publisher,
    source.provider_start_year != null ? `${source.provider_start_year}` : null,
    source.provider_issue_count != null
      ? `${source.provider_issue_count} issues`
      : null,
  ].filter((part): part is string => Boolean(part))
  return meta.length ? `${title} · ${meta.join(' · ')}` : title
}

export interface NewReleasesSectionProps {
  sources: ReadingPlanReleaseSourceStatus[]
  emptyLabel: string
}

/**
 * New releases control for a Reading Plan.
 *
 * The reader can see every followed ComicVine volume and its target Thread,
 * enable a confirmed mapped volume as a release source, and disable it again
 * without deleting comics. Only confirmed/matched ComicVine volume mappings
 * are selectable; ambiguous or unmapped volumes are routed to the existing
 * mapping-repair flow instead of inventing another mapper here.
 *
 * v1 adds issues after ComicVine reports their release date. It does not
 * import future solicitations, discover new series/volumes, or track whether
 * the reader has purchased/downloaded an issue.
 */
export function NewReleasesSection({
  sources,
  emptyLabel,
}: NewReleasesSectionProps) {
  const enable = useEnableReleaseSource()

  if (sources.length === 0) {
    return (
      <section
        aria-labelledby="new-releases-heading"
        className="rounded-xl border border-dashed border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
      >
        <h2
          id="new-releases-heading"
          className="text-base font-bold text-[var(--theme-text-primary)]"
        >
          New releases
        </h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">{emptyLabel}</p>
      </section>
    )
  }

  return (
    <section
      aria-labelledby="new-releases-heading"
      className="space-y-3 rounded-xl border border-[var(--theme-continuity-accent)]/40 bg-[var(--theme-bg-panel)] p-4"
    >
      <div>
        <h2
          id="new-releases-heading"
          className="text-base font-bold text-[var(--theme-text-primary)]"
        >
          New releases
        </h2>
        <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
          v1 adds issues after ComicVine reports their release date. It does not
          import future solicitations, discover new series/volumes, or track
          whether you have purchased or downloaded an issue.
        </p>
      </div>
      <ul className="space-y-2">
        {sources.map((source) => (
          <li
            key={source.source_id}
            data-testid="new-release-source"
            className="flex flex-col gap-2 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-[var(--theme-text-primary)]">
                {volumeLabel(source)}
              </p>
              <p className="truncate text-xs text-[var(--theme-text-muted)]">
                Target thread #{source.thread_id}
              </p>
              <p className="mt-1 text-[11px] text-[var(--theme-text-dim)]">
                Last sync: {formatLastSync(source.last_synced_at)}
              </p>
            </div>
            <button
              type="button"
              aria-pressed={source.enabled}
              disabled={enable.isPending}
              onClick={() => enable.mutate({ sourceId: source.source_id, enabled: !source.enabled })}
              className={`min-h-11 shrink-0 rounded-xl px-3 text-sm font-bold transition disabled:opacity-50 ${
                source.enabled
                  ? 'bg-[var(--theme-primary-action)] text-black hover:bg-[var(--theme-primary-action-hover)]'
                  : 'border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] hover:border-[var(--theme-continuity-accent)]'
              }`}
            >
              {source.enabled ? 'Enabled' : 'Enable'}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default NewReleasesSection