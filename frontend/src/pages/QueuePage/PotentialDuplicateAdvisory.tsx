import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { PotentialDuplicateMatch } from '../../types'

interface PotentialDuplicateAdvisoryProps {
  matches: PotentialDuplicateMatch[]
  /** True while the current candidate is being checked. */
  isChecking?: boolean
  /** True when the advisory lookup failed; the forms stay usable. */
  isError?: boolean
  /**
   * Identity of the current candidate (dialog, title, format, edited thread).
   *
   * Dismissal is remembered per candidate, so editing the title re-arms the
   * advisory instead of keeping a stale "dismissed" state from a previous
   * title.
   */
  candidateKey: string
}

function matchContext(match: PotentialDuplicateMatch): string {
  const parts = [
    match.format,
    match.start_year !== null ? `started ${match.start_year}` : null,
    match.comicvine_volume_id !== null ? `ComicVine volume ${match.comicvine_volume_id}` : null,
    match.issues_remaining > 0 ? `${match.issues_remaining} unread` : 'all read',
  ]
  return parts.filter((part): part is string => part !== null).join(' · ')
}

/**
 * Nonblocking "possible existing volume" advisory for Add Series and
 * Edit/Rename (#3612).
 *
 * The panel only informs: it never disables the submit button and never writes
 * to reader data. Canonical ComicVine identity is labelled as a confirmed
 * volume, while a title resemblance is labelled explicitly uncertain so a
 * same-named relaunch or edition stays creatable.
 */
export function PotentialDuplicateAdvisory({
  matches,
  isChecking = false,
  isError = false,
  candidateKey,
}: PotentialDuplicateAdvisoryProps) {
  const [dismissedKey, setDismissedKey] = useState<string | null>(null)

  if (isError) {
    // The advisory is optional context. A failed lookup must not look like a
    // confirmed absence of duplicates, and must not block the form.
    return null
  }

  if (matches.length === 0) {
    if (!isChecking) return null
    return (
      <p className="text-xs text-[var(--theme-text-dim)]" data-testid="potential-duplicate-checking">
        Checking your library for an existing series…
      </p>
    )
  }

  const advisoryKey = `${candidateKey}|${matches
    .map((match) => `${match.thread_id}:${match.match_type}`)
    .join(',')}`
  if (dismissedKey === advisoryKey) return null

  return (
    <section
      role="status"
      aria-live="polite"
      data-testid="potential-duplicate-advisory"
      className="space-y-2 rounded-xl border border-[var(--theme-warning)]/40 bg-[var(--theme-warning)]/10 p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="space-y-1">
          <p className="text-sm font-bold text-[var(--theme-warning)]">Possible existing series</p>
          <p className="text-xs text-[var(--theme-text-muted)]">
            You can still create or save this. Check whether one of these is the volume you mean.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDismissedKey(advisoryKey)}
          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-2 py-1 text-xs font-bold text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-hover)] hover:text-[var(--theme-text-primary)] transition-colors"
          aria-label="Dismiss possible existing series warning"
        >
          Dismiss
        </button>
      </div>
      <ul className="space-y-2">
        {matches.map((match) => {
          const confirmed = match.match_type === 'same_comicvine_volume'
          return (
            <li
              key={match.thread_id}
              className="space-y-1 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-2"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="min-w-0 break-words text-sm font-semibold text-[var(--theme-text-primary)]">
                  {match.title}
                </span>
                <span className="shrink-0 text-[10px] font-bold uppercase tracking-widest text-[var(--theme-warning)]">
                  {confirmed ? 'Confirmed volume' : 'Uncertain title match'}
                </span>
              </div>
              <p className="text-xs text-[var(--theme-text-muted)]">{matchContext(match)}</p>
              <Link
                to={`/thread/${match.thread_id}`}
                aria-label={`Open existing series ${match.title}`}
                className="inline-block text-xs font-bold text-[var(--theme-comic-accent)] hover:underline"
              >
                Open series #{match.thread_id}
              </Link>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
