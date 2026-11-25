import { Link } from 'react-router-dom'
import { useCreateReleaseSource, useEnableReleaseSource } from '../hooks/useReleaseSources'
import type {
  ReadingPlanReleaseCandidate,
  ReadingPlanReleaseSourceStatus,
} from '../services/api-continuity-plans'

/**
 * The v1 boundary of the new-releases feature.
 *
 * It is shown wherever the section appears — followed volumes, candidates, and
 * the empty state — so the reader always knows what following a volume does
 * and does not do.
 */
const V1_LIMIT_COPY =
  'v1 adds issues after ComicVine reports their release date. It does not import future solicitations, discover new series/volumes, or track whether you have purchased or downloaded an issue.'

/** Canonical mapping-repair route for a thread's ComicVine series mapping. */
const MAPPING_REPAIR_PATH = '/queue'

/** A candidate whose confirmed volume identity is known. */
interface FollowableCandidate extends ReadingPlanReleaseCandidate {
  external_identity_id: number
}

/**
 * Report whether a candidate can be followed right now.
 *
 * @param candidate - Candidate projected by the plan reader view.
 * @returns True when the candidate names a confirmed volume that is not followed.
 */
function isFollowable(candidate: ReadingPlanReleaseCandidate): candidate is FollowableCandidate {
  return candidate.enableable && candidate.external_identity_id != null
}

function formatLastSync(lastSyncedAt: string | null): string {
  if (!lastSyncedAt) return 'Never synced'
  const date = new Date(lastSyncedAt)
  if (Number.isNaN(date.getTime())) return 'Never synced'
  return date.toLocaleString()
}

/** Label used when ComicVine has no human-readable name for a volume. */
const UNKNOWN_VOLUME_LABEL = 'ComicVine volume'

/**
 * Report whether a provider value is only a bare numeric id such as "151520".
 *
 * @param value - Provider-supplied title or volume id.
 * @returns True when the value is only digits.
 */
function isBareNumericId(value: string): boolean {
  return /^\d+$/.test(value.trim())
}

/**
 * Build a human-readable volume title, never exposing a bare provider id.
 *
 * When ComicVine has no usable human name, identify the volume by its plan
 * thread name plus a readable label. If no thread name is available, fall back
 * to the labelled provider id. A bare numeric id is never used as a title.
 *
 * @param providerTitle - ComicVine's human name, when present.
 * @param providerVolumeId - ComicVine volume id, used only in a labelled fallback.
 * @param threadTitle - Plan thread name, used to identify an unnamed volume.
 * @returns A readable title.
 */
function volumeTitle(
  providerTitle: string | null | undefined,
  providerVolumeId?: string | null,
  threadTitle?: string | null,
): string {
  const title = providerTitle?.trim()
  if (title && !isBareNumericId(title)) return title
  const thread = threadTitle?.trim()
  if (thread) return `${thread} · ${UNKNOWN_VOLUME_LABEL}`
  const id = providerVolumeId?.trim()
  return id ? `${UNKNOWN_VOLUME_LABEL} ${id}` : UNKNOWN_VOLUME_LABEL
}

/**
 * Format an issue count with correct singular/plural grammar.
 *
 * @param count - Number of issues in the volume.
 * @returns A count such as "1 issue" or "23 issues".
 */
function formatIssueCount(count: number): string {
  return `${count} ${count === 1 ? 'issue' : 'issues'}`
}

/**
 * Build the full label for a followed volume: title plus provider metadata.
 *
 * @param source - Followed release source to describe.
 * @returns A readable label with publisher, year and issue count when known.
 */
function volumeLabel(source: ReadingPlanReleaseSourceStatus): string {
  const title = volumeTitle(source.provider_title, source.provider_volume_id)
  const meta = [
    source.provider_publisher,
    source.provider_start_year != null ? `${source.provider_start_year}` : null,
    source.provider_issue_count != null ? formatIssueCount(source.provider_issue_count) : null,
  ].filter((part): part is string => Boolean(part))
  return meta.length ? `${title} · ${meta.join(' · ')}` : title
}

/**
 * Build the full label for a release candidate: title plus provider metadata.
 *
 * @param candidate - Release candidate to describe.
 * @returns A readable label with publisher, year and issue count when known.
 */
function candidateLabel(candidate: ReadingPlanReleaseCandidate): string {
  const title = volumeTitle(
    candidate.provider_title,
    candidate.provider_volume_id,
    candidate.thread_title,
  )
  const meta = [
    candidate.provider_publisher,
    candidate.provider_start_year != null ? `${candidate.provider_start_year}` : null,
    candidate.provider_issue_count != null ? formatIssueCount(candidate.provider_issue_count) : null,
  ].filter((part): part is string => Boolean(part))
  return meta.length ? `${title} · ${meta.join(' · ')}` : title
}

export interface NewReleasesSectionProps {
  planId: number
  sources: ReadingPlanReleaseSourceStatus[]
  candidates: ReadingPlanReleaseCandidate[]
}

/**
 * New releases control for a Reading Plan.
 *
 * The reader sees every followed ComicVine volume with its target Thread and
 * last sync state, can follow a confirmed mapped volume in one action, and
 * can stop following a volume again without deleting any comic, issue, or
 * membership. Only confirmed ComicVine volume mappings are selectable;
 * ambiguous or unmapped threads are routed to the existing mapping-repair
 * flow instead of inventing another mapper here.
 *
 * v1 adds issues after ComicVine reports their release date. It does not
 * import future solicitations, discover new series/volumes, or track whether
 * the reader has purchased/downloaded an issue.
 */
export function NewReleasesSection({
  planId,
  sources,
  candidates,
}: NewReleasesSectionProps) {
  const enable = useEnableReleaseSource()
  const follow = useCreateReleaseSource()

  const followable = candidates.filter(isFollowable)
  const blocked = candidates.filter((candidate) => !isFollowable(candidate))
  const hasContent = sources.length > 0 || candidates.length > 0
  const errorMessage = follow.error?.message ?? enable.error?.message

  return (
    <section
      aria-labelledby="new-releases-heading"
      className={`rounded-xl border bg-[var(--theme-bg-panel)] p-4 ${
        hasContent
          ? 'border-[var(--theme-continuity-accent)]/40'
          : 'border-dashed border-[var(--theme-border)]'
      }`}
    >
      <h2
        id="new-releases-heading"
        className="text-base font-bold text-[var(--theme-text-primary)]"
      >
        New releases
      </h2>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">{V1_LIMIT_COPY}</p>

      {errorMessage && (
        <p
          role="alert"
          className="mt-2 text-sm font-semibold text-[var(--theme-danger)]"
        >
          {errorMessage}
        </p>
      )}

      {sources.length > 0 && (
        <ul className="mt-3 space-y-2">
          {sources.map((source) => {
            const title = volumeTitle(source.provider_title, source.provider_volume_id)
            const action = source.enabled ? 'Stop following' : 'Follow'
            return (
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
                  <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
                    Last sync: {formatLastSync(source.last_synced_at)}
                  </p>
                </div>
                <button
                  type="button"
                  aria-pressed={source.enabled}
                  aria-label={`${action} ${title}`}
                  disabled={enable.isPending}
                  onClick={() =>
                    enable.mutate({
                      sourceId: source.source_id,
                      enabled: !source.enabled,
                    })
                  }
                  className={`min-h-11 shrink-0 rounded-xl px-3 text-sm font-bold transition disabled:opacity-50 ${
                    source.enabled
                      ? 'bg-[var(--theme-primary-action)] text-black hover:bg-[var(--theme-primary-action-hover)]'
                      : 'border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)] hover:border-[var(--theme-continuity-accent)]'
                  }`}
                >
                  {action}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {followable.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-bold text-[var(--theme-text-primary)]">
            Available to follow
          </h3>
          <ul className="mt-2 space-y-2">
            {followable.map((candidate) => {
              const title = volumeTitle(
                candidate.provider_title,
                candidate.provider_volume_id,
                candidate.thread_title,
              )
              return (
                <li
                  key={`${candidate.thread_id}-${candidate.external_identity_id}`}
                  data-testid="new-release-candidate"
                  className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between surface-panel"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[var(--theme-text-primary)]">
                      {candidateLabel(candidate)}
                    </p>
                    <p className="truncate text-xs text-[var(--theme-text-muted)]">
                      Target thread #{candidate.thread_id} · {candidate.thread_title}
                    </p>
                    <p className="mt-1 text-[11px] text-[var(--theme-text-dim)]">
                      Confirmed ComicVine mapping · not followed yet
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={`Follow ${title}`}
                    disabled={follow.isPending}
                    onClick={() =>
                      follow.mutate({
                        plan_id: planId,
                        thread_id: candidate.thread_id,
                        external_identity_id: candidate.external_identity_id,
                      })
                    }
                    className="min-h-11 shrink-0 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm font-bold text-[var(--theme-text-primary)] transition hover:border-[var(--theme-continuity-accent)] disabled:opacity-50"
                  >
                    Follow
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}

      {blocked.length > 0 && (
        <>
          <h3 className="mt-4 text-sm font-bold text-[var(--theme-text-primary)]">
            Needs a confirmed mapping
          </h3>
          <ul className="mt-2 space-y-2">
            {blocked.map((candidate) => {
              const needsReview = candidate.mapping_state === 'ambiguous'
              return (
                <li
                  key={`blocked-${candidate.thread_id}-${candidate.external_identity_id ?? 0}`}
                  data-testid="new-release-blocked-candidate"
                  className="p-3 surface-panel"
                >
                  <p className="truncate text-sm font-semibold text-[var(--theme-text-primary)]">
                    {candidate.provider_volume_id
                      ? candidateLabel(candidate)
                      : candidate.thread_title}
                  </p>
                  <p className="truncate text-xs text-[var(--theme-text-muted)]">
                    Target thread #{candidate.thread_id} · {candidate.thread_title}
                  </p>
                  <p className="mt-1 text-[11px] text-[var(--theme-text-dim)]">
                    {needsReview
                      ? 'This volume mapping is not confirmed yet, so it cannot be followed.'
                      : 'No ComicVine volume is mapped to this thread yet, so it cannot be followed.'}
                    {candidate.external_identity_id === null ? (
                      <>
                        {' '}
                        Track issues in this thread first, then map its series to follow new
                        releases.
                      </>
                    ) : (
                      <>
                        {' '}
                        <Link
                          to={MAPPING_REPAIR_PATH}
                          className="text-[var(--theme-continuity-accent)] underline hover:text-[var(--theme-text-primary)]"
                        >
                          Repair the mapping
                        </Link>
                      </>
                    )}
                  </p>
                </li>
              )
            })}
          </ul>
        </>
      )}

      {!hasContent && (
        <p className="mt-2 text-sm text-[var(--theme-text-muted)]">
          No ComicVine volumes are followed for new releases in this plan yet.{' '}
          <Link
            to={MAPPING_REPAIR_PATH}
            className="text-[var(--theme-continuity-accent)] underline hover:text-[var(--theme-text-primary)]"
          >
            Queue mapping repair
          </Link>{' '}
          maps a series to a thread, and a confirmed volume can be followed here.
        </p>
      )}
    </section>
  )
}

export default NewReleasesSection
