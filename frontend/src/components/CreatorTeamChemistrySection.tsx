import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { creatorRoutePath } from '../utils/creatorKey'
import type {
  CreatorTeamChemistryResponse,
  CreatorTeamMember,
  CreatorTeamPair,
} from '../types/index'

const FOCUS_RING =
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]'

function formatRating(value: number): string {
  return Number.isInteger(value) ? value.toFixed(1) : value.toFixed(2)
}

function formatDifference(value: number): string {
  const rounded = value.toFixed(2)
  return rounded.startsWith('-') ? rounded : `+${rounded}`
}

function RatingValue({ value, label }: { value: number; label: string }) {
  return (
    <span
      className="font-bold"
      style={{ color: 'var(--theme-personal-accent)' }}
      aria-label={label}
    >
      {formatRating(value)}★
    </span>
  )
}

function CreatorLink({ member }: { member: CreatorTeamMember }) {
  return (
    <Link
      to={creatorRoutePath(member.canonical_creator_key)}
      className={`min-w-0 break-words text-sm font-bold ${FOCUS_RING}`}
      style={{ color: 'var(--theme-text-primary)' }}
    >
      {member.display_name}
    </Link>
  )
}

function MemberBaselineContext({
  pair,
  member,
}: {
  pair: CreatorTeamPair
  member: CreatorTeamMember
}) {
  const baseline =
    member.baseline_average_rating != null ? (
      <>
        baseline{' '}
        <RatingValue
          value={member.baseline_average_rating}
          label={`${member.display_name} baseline average rating ${member.baseline_average_rating} out of 5 from ${member.baseline_rated_count} rated issues`}
        />
      </>
    ) : (
      <span>no rated baseline yet</span>
    )
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
      <span>
        {member.baseline_rated_count} rated in your library
      </span>
      <span>{baseline}</span>
      {pair.shared_average_rating != null && member.difference_from_baseline != null && (
        <span
          aria-label={`Together this pair averages ${pair.shared_average_rating} out of 5, ${member.difference_from_baseline} against ${member.display_name}'s baseline`}
        >
          together{' '}
          <RatingValue
            value={pair.shared_average_rating}
            label={`Shared average rating ${pair.shared_average_rating} out of 5`}
          />{' '}
          ({formatDifference(member.difference_from_baseline)} vs baseline)
        </span>
      )}
      {member.roles.length > 0 && <span className="break-words">{member.roles.join(', ')}</span>}
    </span>
  )
}

function IssueRefs({ pair }: { pair: CreatorTeamPair }) {
  if (pair.shared_issue_refs.length === 0) {
    return null
  }
  return (
    <span className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
      <span>Shared issues:</span>
      {pair.shared_issue_refs.map((ref) => (
        <Link
          key={ref.issue_id}
          to={`/thread/${ref.thread_id}`}
          className={`rounded ${FOCUS_RING}`}
          style={{ color: 'var(--theme-text-primary)' }}
          aria-label={`${ref.thread_title} issue ${ref.issue_number}${
            ref.effective_rating != null ? `, rated ${ref.effective_rating} out of 5` : ''
          }`}
        >
          <span className="underline decoration-dotted underline-offset-2">
            {ref.thread_title} #{ref.issue_number}
          </span>
          {ref.effective_rating != null && (
            <span style={{ color: 'var(--theme-personal-accent)' }}> {formatRating(ref.effective_rating)}★</span>
          )}
        </Link>
      ))}
      {pair.shared_rated_issue_count > pair.max_shared_issue_refs && (
        <span>
          +{pair.shared_rated_issue_count - pair.max_shared_issue_refs} more
        </span>
      )}
    </span>
  )
}

function PairRow({ pair }: { pair: CreatorTeamPair }) {
  return (
    <li className="min-w-0 rounded-xl border px-3 py-2" style={{ borderColor: 'var(--theme-border)', backgroundColor: 'var(--theme-bg-panel)' }}>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        {pair.creators.map((member, index) => (
          <span key={member.canonical_creator_key} className="flex min-w-0 items-center gap-x-2">
            {index > 0 && (
              <span className="text-xs font-bold" style={{ color: 'var(--theme-text-dim)' }} aria-hidden="true">
                +
              </span>
            )}
            <CreatorLink member={member} />
          </span>
        ))}
      </div>
      <div className="mt-1 space-y-1">
        {pair.creators.map((member) => (
          <MemberBaselineContext key={member.canonical_creator_key} pair={pair} member={member} />
        ))}
      </div>
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        <span
          aria-label={`${pair.shared_rated_issue_count} shared rated issues for this team`}
        >
          {pair.shared_rated_issue_count} shared rated issue
          {pair.shared_rated_issue_count === 1 ? '' : 's'}
        </span>
      </div>
      <IssueRefs pair={pair} />
    </li>
  )
}

function SectionShell({ id, heading, children }: { id: string; heading: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="mt-6">
      <h2 id={id} className="text-base font-bold md:text-lg" style={{ color: 'var(--theme-text-primary)' }}>
        {heading}
      </h2>
      {children}
    </section>
  )
}

/**
 * Explainable recurring-creator-team section (issue #3094).
 *
 * Renders ranked canonical creator pairs from one bounded API response. Every
 * shared average carries its sample size and baseline context, drilldown
 * references link to the actual threads behind the pair, and the copy only
 * ever describes differences — never causes or statistical significance.
 *
 * With `forCreatorKey` set (creator detail), the section shows only the teams
 * this creator belongs to; unset (creator discovery) it shows the library's
 * top ranked teams.
 */
export default function CreatorTeamChemistrySection({
  data,
  forCreatorKey,
  heading = 'Team chemistry',
}: {
  data: CreatorTeamChemistryResponse
  forCreatorKey?: string | null
  heading?: string
}) {
  const matched = forCreatorKey
    ? data.pairs.filter((pair) =>
        pair.creators.some((member) => member.canonical_creator_key === forCreatorKey),
      )
    : data.pairs

  if (matched.length === 0) {
    return (
      <SectionShell id={`${forCreatorKey ?? 'creators'}-team-chemistry-heading`} heading={heading}>
        <p className="mt-2 text-sm" style={{ color: 'var(--theme-text-muted)' }}>
          No recurring creator teams yet. Teams appear once two creators share
          your ratings on at least {data.min_shared_team_sample} issues with
          story or interior art credits.
        </p>
      </SectionShell>
    )
  }

  const partialMetadata = data.coverage != null && !data.coverage.ratings_complete

  return (
    <SectionShell id={`${forCreatorKey ?? 'creators'}-team-chemistry-heading`} heading={heading}>
      <ul className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {matched.map((pair) => (
          <PairRow key={pair.pair_key} pair={pair} />
        ))}
      </ul>
      {partialMetadata && (
        <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }} role="note">
          Partial results: some rated issues are still missing confirmed creator metadata. Counts shown are lower bounds, not exhaustive totals.
        </p>
      )}
      <p className="mt-2 text-xs" style={{ color: 'var(--theme-text-muted)' }}>
        Descriptive context from your own ratings. Differences between
        collaborators describe what you rated, not causes or statistically
        significant effects.
      </p>
    </SectionShell>
  )
}
