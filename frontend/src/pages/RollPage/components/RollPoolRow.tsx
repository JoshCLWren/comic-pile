import { useState } from 'react'
import { ThreadTagChips } from '../../../components/Tags/ThreadTagChips'
import type { RollPoolRow as RollPoolRowModel } from '../../../types/rollBootstrap'
import {
  rollGroupNames,
  rollIdentityStatusCopy,
  rollProgressCopy,
  rollRatingCopy,
} from '../rollPoolRowCopy'

interface RollPoolRowProps {
  row: RollPoolRowModel
  dieFace: number
  isSelected: boolean
  onClick: () => void
}

/**
 * One comic-first idle Roll pool row.
 *
 * The row makes the comic recognizable from a single v2 bootstrap payload:
 * cover, thread title plus exact next issue number, compact format, canonical
 * rating context, truthful scoped progress, and bounded group names. Every
 * decorative field is optional and collapses cleanly when provider data is
 * absent, so a row without a cover, canonical identity, rating history, or run
 * length still reads honestly.
 */
export function RollPoolRow({ row, dieFace, isSelected, onClick }: RollPoolRowProps) {
  const [failedCoverUrl, setFailedCoverUrl] = useState<string | null>(null)
  const coverUrl = row.cover_url ?? null
  const showCover = coverUrl !== null && coverUrl !== failedCoverUrl
  const tags = row.tags ?? []
  const tagNames = tags.map((tag) => tag.name)
  const groups = rollGroupNames(row)
  const overflowRoutes = row.overflow_routes_count ?? 0
  const progress = rollProgressCopy(row)
  const ratings = rollRatingCopy(row)
  const identityState = row.identity_state ?? null
  const statusCopy = rollIdentityStatusCopy(identityState)
  const issueLabel = row.issue_number ? `#${row.issue_number}` : 'Next unread issue'
  const canonicalTitle =
    row.canonical_series_title && row.canonical_series_title !== row.title
      ? row.canonical_series_title
      : null
  const ariaParts = [
    `Die face ${dieFace}: ${row.title}`,
    row.issue_number ? `issue ${row.issue_number}` : null,
    row.format || null,
    tagNames.length ? `tagged ${tagNames.join(', ')}` : null,
    groups.length ? `groups ${groups.join(', ')}` : null,
    statusCopy,
  ].filter((part): part is string => part !== null)

  return (
    <div
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick()
        }
      }}
      role="button"
      tabIndex={0}
      aria-label={`${ariaParts.join(', ')}. Open series actions.`}
      data-testid="roll-pool-row"
      data-identity-state={identityState ?? undefined}
      className={`flex items-start gap-3 px-3 py-3 md:px-4 bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] rounded-xl group transition-all cursor-pointer hover:bg-white/10 ${
        isSelected ? 'pool-thread-selected border-[var(--theme-comic-accent)]/30' : ''
      }`}
    >
      <span className="w-6 shrink-0 text-center text-lg font-black text-[var(--theme-text-dim)]/60 group-hover:text-[var(--theme-text-dim)] transition-colors">
        {dieFace}
      </span>

      <div className="w-10 md:w-12 shrink-0 overflow-hidden rounded-md border border-[var(--theme-border)] bg-white/5 aspect-[2/3]">
        {showCover ? (
          <img
            src={coverUrl}
            alt=""
            loading="lazy"
            decoding="async"
            data-testid="roll-pool-cover"
            onError={() => setFailedCoverUrl(coverUrl)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div
            data-testid="roll-pool-cover-placeholder"
            aria-hidden="true"
            className="flex h-full w-full items-center justify-center text-[var(--theme-text-dim)]"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25"
              />
            </svg>
          </div>
        )}
      </div>

      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
          <p
            className="min-w-0 max-w-full truncate text-sm font-bold text-[var(--theme-text-primary)]"
            title={row.title}
          >
            {row.title}
          </p>
          <span className="shrink-0 text-xs font-semibold text-[var(--theme-text-muted)] tabular-nums">
            {issueLabel}
          </span>
          {statusCopy ? (
            <span
              data-testid="roll-pool-identity-status"
              className="shrink-0 rounded-full border border-[var(--theme-warning)]/40 bg-[var(--theme-warning)]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--theme-warning)]"
            >
              {statusCopy}
            </span>
          ) : null}
        </div>

        <p className="truncate text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-dim)]">
          {row.format || 'Format unknown'}
          {canonicalTitle ? (
            <span className="normal-case font-medium tracking-normal text-[var(--theme-text-muted)]">
              {' '}
              · {canonicalTitle}
            </span>
          ) : null}
        </p>

        {ratings ? (
          <p
            data-testid="roll-pool-ratings"
            className="text-xs text-[var(--theme-personal-accent)] tabular-nums"
          >
            {ratings}
          </p>
        ) : null}

        {progress ? (
          <p
            data-testid="roll-pool-progress"
            className="text-xs text-[var(--theme-text-muted)] tabular-nums"
          >
            {progress}
          </p>
        ) : null}

        {groups.length ? (
          <p
            data-testid="roll-pool-groups"
            className="truncate text-[11px] text-[var(--theme-continuity-accent)]"
          >
            Groups · {groups.join(' · ')}
            {overflowRoutes > 0 ? ` · +${overflowRoutes} more` : ''}
          </p>
        ) : null}

        <ThreadTagChips tags={tags} label={`Tags for ${row.title}`} className="mt-1" />
      </div>
    </div>
  )
}
