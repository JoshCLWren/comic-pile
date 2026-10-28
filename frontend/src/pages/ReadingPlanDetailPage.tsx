import { displayCblRepository, displayCblSourcePath, displayCblSourceTitle, displayReadingListName } from '../utils/cblSourceDisplay'
import { ReaderIssueActions } from '../components/ReaderIssueActions'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryKeys } from '../query/queryKeys'
import { customCBLApi } from '../services/api-custom-cbl'
import { verifiedOwnedReadingListForPlan } from '../utils/ownedReadingListPlanMatch'
import { threadIssueRoutePath } from '../utils/threadRoutes'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import ReadingPlanAddMaterial from '../components/ReadingPlanAddMaterial'
import { NewReleasesSection } from '../components/NewReleasesSection'
import { TagSection } from '../components/Tags/TagSection'
import { useReadingPlanReader } from '../hooks/useReadingPlans'
import {
  readingPlanModeLabel,
  type ReadingPlanReaderIssue,
} from '../services/api-continuity-plans'

function progressPercent(read: number, total: number): number {
  if (total <= 0) return 0
  return Math.round((read / total) * 100)
}

function issueLabel(issue: ReadingPlanReaderIssue): string {
  return issue.label?.trim() ? issue.label : `${issue.thread_title} #${issue.issue_number}`
}

function availabilityLabel(issue: ReadingPlanReaderIssue): string {
  if (issue.availability === 'excluded') return 'Excluded from collection'
  if (issue.availability === 'inactive') return 'Series is inactive'
  if (issue.availability === 'read') return 'Read'
  if (issue.availability === 'blocked') return 'Blocked by'
  if (issue.availability === 'available') return 'Available now'
  return 'Upcoming'
}

/** Keep the first actionable prerequisite visible; never eagerly render 400+ dependency links. */
function PlanIssueBlockers({ blockers }: { blockers: ReadingPlanReaderIssue['blockers'] }) {
  const [expanded, setExpanded] = useState(false)
  const first = blockers[0]
  if (!first) return null
  const remaining = blockers.length - 1
  return (
    <div className="mt-2 text-sm text-[var(--theme-text-muted)]" data-testid="plan-issue-blockers">
      <p>
        Read{' '}
        <Link
          aria-label={`Open ${first.thread_title} issue #${first.issue_number}`}
          to={threadIssueRoutePath(first.thread_id, first.issue_id)}
          className="font-semibold text-[var(--theme-continuity-accent)] underline"
        >
          {first.thread_title} #{first.issue_number}
        </Link>{' '}
        first.
      </p>
      {remaining > 0 && (
        <>
          <button
            type="button"
            className="mt-1 min-h-9 text-xs font-semibold text-[var(--theme-continuity-accent)] underline"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? 'Hide' : 'Show'} {remaining} other reading requirements
          </button>
          {expanded && (
            <ul className="mt-2 space-y-2" aria-label="Other reading requirements">
              {blockers.slice(1).map((blocker, index) => (
                <li key={`${blocker.issue_id}-${index}`}>
                  <Link
                    aria-label={`Open ${blocker.thread_title} issue #${blocker.issue_number}`}
                    to={threadIssueRoutePath(blocker.thread_id, blocker.issue_id)}
                    className="text-[var(--theme-continuity-accent)] underline"
                  >
                    {blocker.thread_title} #{blocker.issue_number}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

function IssueRow({ issue, sourceNames }: { issue: ReadingPlanReaderIssue; sourceNames: Readonly<Record<string, string>> }) {
  const isRead = issue.availability === 'read'
  const isBlocked = issue.availability === 'blocked'
  const isAvailable = issue.availability === 'available'
  return (
    <li
      data-testid="reading-plan-issue-row"
      className={
        'flex flex-col gap-2 rounded-xl border p-3 sm:flex-row sm:items-center ' +
        (isRead
          ? 'border-[var(--theme-border)] bg-[var(--theme-bg-panel)]'
          : isBlocked
            ? 'border-[var(--theme-warning)]/40 bg-[var(--theme-warning)]/10'
            : isAvailable
              ? 'border-[var(--theme-continuity-accent)]/40 bg-[var(--theme-continuity-accent)]/10'
              : 'border-[var(--theme-border)] bg-[var(--theme-bg-panel)]')
      }
    >
      <div className="min-w-0 flex-1">
        <p
          className={`truncate font-medium ${isRead ? 'text-[var(--theme-text-muted)] line-through' : 'text-[var(--theme-text-primary)]'}`}
        >
          {issueLabel(issue)}
        </p>
        <p className="truncate text-sm text-[var(--theme-text-muted)]">
          {issue.thread_title}
          {isAvailable ? ' · Next unread issue #' : ' · Issue #'}
          {issue.issue_number}
          {issue.is_checkpoint ? ' · Checkpoint' : ''}
        </p>
        {issue.blockers.length > 0 && <PlanIssueBlockers blockers={issue.blockers} />}
        <ReaderIssueActions issueId={issue.issue_id} threadId={issue.thread_id} issueNumber={issue.issue_number} isRead={isRead} available={isAvailable} />
        {issue.source_paths.length > 0 && (
          <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
            Source reading order: {sourceNames[issue.source_paths[0]] ?? displayCblSourceTitle(null, issue.source_paths[0]) ?? 'Reading order'}
            {issue.source_paths.length > 1 ? ` +${issue.source_paths.length - 1} more` : ''}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={
            'rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ' +
            (isRead
              ? 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-muted)]'
              : isBlocked
                ? 'text-[var(--theme-warning)]'
                : isAvailable
                  ? 'text-[var(--theme-continuity-accent)]'
                  : 'text-[var(--theme-text-dim)]')
          }
        >
          {availabilityLabel(issue)}
        </span>
        <Link
          to={`/thread/${issue.thread_id}`}
          className="min-h-11 inline-flex items-center rounded-xl px-3 text-sm font-bold text-[var(--theme-continuity-accent)] hover:text-[var(--theme-text-primary)]"
        >
          Open
        </Link>
      </div>
    </li>
  )
}

export default function ReadingPlanDetailPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const addFromCblRequested = searchParams.get('addFrom') === 'cbl'
  const [showReleaseTracking, setShowReleaseTracking] = useState(false)
  const [visibleBlockedCount, setVisibleBlockedCount] = useState(3)
  const [showUpcoming, setShowUpcoming] = useState(false)
  const [visibleUpcomingCount, setVisibleUpcomingCount] = useState(30)
  const [showReadingOrder, setShowReadingOrder] = useState(false)
  const [visibleOrderCount, setVisibleOrderCount] = useState(40)
  const parsedId = id ? Number(id) : null
  const planId = parsedId && Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null
  const readerQuery = useReadingPlanReader(planId)
  // Some migrated Reading Plans retain only a legacy source (e.g. a ComicVine
  // volume) even though an owned, authoritatively ordered Reading List exists.
  // Resolve a unique same-name owned list and check its issue membership before
  // offering it as an editor; never infer ownership or mutate plan provenance.
  const legacySourceOnly = readerQuery.isSuccess && !readerQuery.data.sources.some(
    (source) => source.display_name != null && /^custom-cbl:[1-9][0-9]*$/.test(source.raw_source_path),
  )
  const ownedListsQuery = useQuery({
    queryKey: queryKeys.customCBLs.list(),
    queryFn: customCBLApi.list,
    enabled: planId != null && legacySourceOnly,
  })
  const matchingName = readerQuery.data?.name.trim().toLocaleLowerCase()
  const sameName = ownedListsQuery.data?.filter((list) =>
    list.name.trim().toLocaleLowerCase() === matchingName,
  ) ?? []
  const potentialListId = sameName.length === 1 ? sameName[0].id : null
  const potentialListQuery = useQuery({
    queryKey: queryKeys.customCBLs.detail(potentialListId ?? 0),
    queryFn: () => customCBLApi.get(potentialListId!),
    enabled: legacySourceOnly && potentialListId != null,
  })

  if (planId == null) {
    return (
      <div role="alert" className="rounded-2xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-4 text-[var(--theme-danger)]">
        Invalid reading plan ID.
      </div>
    )
  }

  if (readerQuery.isPending) {
    return (
      <p role="status" className="text-[var(--theme-text-muted)]">
        Loading Reading Plan…
      </p>
    )
  }

  if (readerQuery.isError || !readerQuery.data) {
    return (
      <div role="alert" className="rounded-2xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-4 text-[var(--theme-danger)]">
        <p>{readerQuery.error?.message || 'Unable to load this Reading Plan.'}</p>
        <button
          type="button"
          onClick={() => void readerQuery.refetch()}
          className="mt-3 min-h-11 rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black"
        >
          Try again
        </button>
      </div>
    )
  }

  const view = readerQuery.data
  const sourceNames = Object.fromEntries(view.sources.map((source) => [
    source.raw_source_path,
    displayReadingListName(source.display_name, source.source_path ?? source.raw_source_path) ?? 'Reading order',
  ]))
  // Only an owned custom-CBL source gets a resolved display_name from the backend.
  // The immutable custom-cbl:<id> reference is enough to navigate without
  // exposing cross-reader list IDs in a new API field.
  const ownedListSource = view.sources.find((source) =>
    source.display_name != null && /^custom-cbl:[1-9][0-9]*$/.test(source.raw_source_path),
  )
  const candidateListId = ownedListSource ? Number(ownedListSource.raw_source_path.slice('custom-cbl:'.length)) : null
  const linkedListId = candidateListId != null && Number.isSafeInteger(candidateListId) ? candidateListId : null
  const fallbackListId = legacySourceOnly && ownedListsQuery.data
    ? verifiedOwnedReadingListForPlan(
      view.name,
      view.lanes.flatMap((lane) => lane.issues.map((issue) => issue.issue_id)),
      ownedListsQuery.data,
      potentialListQuery.data ?? null,
    )
    : null
  const editableListId = linkedListId ?? fallbackListId
  const modeLabel = readingPlanModeLabel(view.ordering_mode)
  const isStrict = view.ordering_mode === 'strict_sequential'
  const percent = progressPercent(view.progress.read_issues, view.progress.total_issues)
  const remaining = Math.max(view.progress.total_issues - view.progress.read_issues, 0)
  const continueIssue = view.available_now[0] ?? null
  const upcoming = view.lanes.flatMap((lane) =>
    lane.issues.filter((issue) => issue.availability === 'later'),
  )
  const totalOrderIssues = view.lanes.reduce((count, lane) => count + lane.issues.length, 0)
  let visibleOrderRemaining = visibleOrderCount
  const visibleOrderLanes = view.lanes.flatMap((lane) => {
    const visibleIssues = lane.issues.slice(0, visibleOrderRemaining)
    visibleOrderRemaining = Math.max(0, visibleOrderRemaining - visibleIssues.length)
    return visibleIssues.length ? [{ ...lane, issues: visibleIssues }] : []
  })

  return (
    <section className="space-y-6 pb-8" aria-labelledby="reading-plan-heading" data-testid="reading-plan-reader">
      <Breadcrumbs
        items={[{ label: 'Reading plans', to: '/continuity-plans' }, { label: view.name }]}
      />

      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--theme-continuity-accent)]">
            {modeLabel}
          </p>
          <h1 id="reading-plan-heading" className="text-2xl font-black text-[var(--theme-text-primary)]">
            {view.name}
          </h1>
          <p className="mt-2 text-sm text-[var(--theme-text-muted)]">
            {view.execution_mode === 'option_e'
              ? 'Availability follows your Reading Lists, series order, collection exclusions and explicit prerequisites, just as Roll and Queue do.'
              : isStrict
              ? 'Strict records intent for selected hard prerequisites; compiling them from plan order is not active yet. Source reading order is not a blocker by itself.'
              : 'Informational: this is a reading reference. Source reading order adds no hard blockers.'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {continueIssue && (
            <Link
              to={`/thread/${continueIssue.thread_id}`}
              className="inline-flex min-h-11 items-center justify-center rounded-xl bg-[var(--theme-primary-action)] px-4 text-sm font-black text-black hover:bg-[var(--theme-primary-action-hover)]"
            >
              Continue reading
            </Link>
          )}
          <button
            type="button"
            disabled={legacySourceOnly && (ownedListsQuery.isPending || (potentialListId != null && potentialListQuery.isPending))}
            onClick={() => navigate(editableListId != null ? `/reading-lists/${editableListId}` : `/continuity-plans/${planId}/edit`)}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            {editableListId != null ? 'Edit reading order' : 'Edit plan'}
          </button>
        </div>
      </header>

      <div
        className="surface-panel rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 sm:px-6 sm:py-4"
        data-testid="plan-progress"
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4 sm:gap-y-0 sm:divide-x sm:divide-[var(--theme-border)]">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Issues</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">{view.progress.total_issues}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Read</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-continuity-accent)]">{view.progress.read_issues}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Remaining</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">{remaining}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Progress</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">{percent}%</dd>
          </div>
        </dl>
      </div>

      <section aria-labelledby="available-now-heading" data-testid="available-now">
        <h2 id="available-now-heading" className="text-lg font-bold text-[var(--theme-text-primary)]">
          Available now
        </h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Next unread issues in this plan with no unread prerequisite.
        </p>
        {view.available_now.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--theme-text-dim)]">
            {view.progress.total_issues === 0
              ? 'This plan has no issues yet. Add material from a source reading order or edit the plan.'
              : remaining === 0
                ? 'Every issue in this plan is read.'
                : 'Nothing in this plan is currently available. Check Blocked next for the comics holding the rest back.'}
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {view.available_now.map((issue) => (
              <IssueRow key={issue.occurrence_id} issue={issue} sourceNames={sourceNames} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="blocked-next-heading" data-testid="blocked-next">
        <h2 id="blocked-next-heading" className="text-lg font-bold text-[var(--theme-text-primary)]">
          Blocked next
        </h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Next unread issues waiting on the reading requirements shown below.
        </p>
        {view.blocked_next.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--theme-text-dim)]">No hard blockers on the next unread issues in this plan.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {view.blocked_next.slice(0, visibleBlockedCount).map((issue) => (
              <IssueRow key={issue.occurrence_id} issue={issue} sourceNames={sourceNames} />
            ))}
          </ul>
        )}
        {view.blocked_next.length > 3 && (
          <button
            type="button"
            className="mt-3 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
            onClick={() => setVisibleBlockedCount((count) =>
              count >= view.blocked_next.length ? 3 : Math.min(count + 10, view.blocked_next.length),
            )}
          >
            {visibleBlockedCount >= view.blocked_next.length
              ? 'Show fewer blocked issues'
              : `Show ${Math.min(10, view.blocked_next.length - visibleBlockedCount)} more blocked issues`}
          </button>
        )}
      </section>

      {upcoming.length > 0 && (
        <section aria-labelledby="upcoming-heading" data-testid="upcoming-material">
          <h2 id="upcoming-heading" className="text-lg font-bold text-[var(--theme-text-primary)]">
            Upcoming
          </h2>
          <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
            Later issues still behind this series’ next unread issue.
          </p>
          <button
            type="button"
            className="mt-2 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
            aria-expanded={showUpcoming}
            onClick={() => setShowUpcoming((value) => !value)}
          >
            {showUpcoming ? 'Hide upcoming issues' : `Show ${upcoming.length} upcoming issues`}
          </button>
          {showUpcoming && (
            <ul className="mt-3 space-y-2">
              {upcoming.slice(0, visibleUpcomingCount).map((issue) => (
                <IssueRow key={issue.occurrence_id} issue={issue} sourceNames={sourceNames} />
              ))}
            </ul>
          )}
          {showUpcoming && upcoming.length > visibleUpcomingCount && (
            <button type="button" className="mt-2 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
              onClick={() => setVisibleUpcomingCount((count) => count + 30)}>
              Show next {Math.min(30, upcoming.length - visibleUpcomingCount)} upcoming issues
            </button>
          )}
        </section>
      )}

      {view.sources.length > 0 && (
        <section
          className="rounded-xl border border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)] p-4"
          aria-labelledby="plan-sources-heading"
        >
          <h2 id="plan-sources-heading" className="text-sm font-black text-[var(--theme-continuity-accent)]">
            Source reading order
          </h2>
          <p className="mt-1 text-xs font-black text-[var(--theme-continuity-accent)]">CBL-backed</p>
          <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
            {view.execution_mode === 'option_e'
              ? 'This linked Reading List controls reading eligibility in Roll, Queue, and this plan.'
              : 'Where this plan’s source material came from. Source order does not add hard blockers in legacy mode.'}
          </p>
          <ul className="mt-2 space-y-1 text-sm text-[var(--theme-text-primary)]">
            {view.sources.map((source) => {
              const path = displayCblSourcePath(source.source_path ?? source.raw_source_path)
              const repository = source.repository ? displayCblRepository(source.repository) : null
              return (
                <li key={source.id}>
                  <p>{sourceNames[source.raw_source_path]}</p>
                  {(path || repository || source.revision_sha) && (
                    <details className="mt-1 text-xs text-[var(--theme-text-dim)]">
                      <summary className="cursor-pointer font-bold text-[var(--theme-text-muted)]">Source details</summary>
                      <div className="mt-2 space-y-1 break-words">
                        {path && <p>{path}</p>}
                        {repository && <p>{repository}</p>}
                        {source.revision_sha && <p>Revision {source.revision_sha.slice(0, 8)}</p>}
                      </div>
                    </details>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <ReadingPlanAddMaterial
        planId={planId}
        planName={view.name}
        defaultOpen={addFromCblRequested}
      />

      <section
        aria-label="Reading Plan tags"
        className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-4"
      >
        <TagSection targetType="ContinuityPlan" targetId={planId} targetLabel={view.name} />
      </section>

      <section aria-labelledby="reading-order-heading">
        <h2 id="reading-order-heading" className="text-lg font-bold text-[var(--theme-text-primary)]">
          Reading order
        </h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Series lanes in plan order. Same-series neighbors follow the series’ next unread issue, not
          a list of extra blockers.
        </p>
        {view.lanes.length === 0 || view.lanes.every((lane) => lane.issues.length === 0) ? (
          <p className="mt-3 text-sm text-[var(--theme-text-dim)]">No issues in this reading order yet.</p>
        ) : (
          <>
          <button
            type="button"
            className="mt-2 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
            aria-expanded={showReadingOrder}
            onClick={() => setShowReadingOrder((value) => !value)}
          >
            {showReadingOrder ? 'Hide complete reading order' : `Show complete reading order (${view.progress.total_issues} issues)`}
          </button>
          {showReadingOrder && <div className="mt-4 space-y-6">
            {visibleOrderLanes.map((lane) => (
              <section key={lane.id} aria-labelledby={`lane-${lane.id}-heading`} className="space-y-2">
                <h3 id={`lane-${lane.id}-heading`} className="text-base font-bold text-[var(--theme-text-primary)]">
                  {lane.name}
                </h3>
                {lane.issues.length === 0 ? (
                  <p className="text-sm text-[var(--theme-text-dim)]">This lane is empty.</p>
                ) : (
                  <ul className="space-y-2">
                    {lane.issues.map((issue) => (
                      <IssueRow key={issue.occurrence_id} issue={issue} sourceNames={sourceNames} />
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>}
          {showReadingOrder && totalOrderIssues > visibleOrderCount && (
            <button type="button" className="mt-3 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
              onClick={() => setVisibleOrderCount((count) => count + 40)}>
              Show next {Math.min(40, totalOrderIssues - visibleOrderCount)} issues in reading order
            </button>
          )}
          </>
        )}
      </section>

      <section aria-label="Optional release tracking" className="surface-panel p-4">
        <h2 className="text-base font-bold text-[var(--theme-text-primary)]">Optional: Track future releases</h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Subscribing to ComicVine volumes is separate from the reading order and is not required to read any of these comics.
        </p>
        <button
          type="button"
          className="mt-2 min-h-11 text-sm font-semibold text-[var(--theme-continuity-accent)] underline"
          aria-expanded={showReleaseTracking}
          onClick={() => setShowReleaseTracking((value) => !value)}
        >
          {showReleaseTracking ? 'Hide release tracking' : 'Manage release tracking'}
        </button>
        {showReleaseTracking && (
          <div className="mt-3">
            <NewReleasesSection
              planId={planId}
              sources={view.release_sources ?? []}
              candidates={view.release_candidates ?? []}
            />
          </div>
        )}
      </section>
    </section>
  )
}
