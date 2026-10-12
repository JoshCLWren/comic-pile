import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import ReadingPlanAddMaterial from '../components/ReadingPlanAddMaterial'
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
  if (issue.availability === 'read') return 'Read'
  if (issue.availability === 'blocked') return 'Blocked by'
  if (issue.availability === 'available') return 'Available now'
  return 'Upcoming'
}

function IssueRow({ issue }: { issue: ReadingPlanReaderIssue }) {
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
        {issue.blockers.length > 0 && (
          <ul className="mt-1 space-y-0.5" aria-label={`Blocked by for ${issueLabel(issue)}`}>
            {issue.blockers.map((blocker) => (
              <li key={blocker.issue_id} className="text-sm text-[var(--theme-warning)]">
                {blocker.explanation}
              </li>
            ))}
          </ul>
        )}
        {issue.source_paths.length > 0 && (
          <p className="mt-1 text-xs text-[var(--theme-text-dim)]">
            Source reading order: {issue.source_paths[0]}
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
  const parsedId = id ? Number(id) : null
  const planId = parsedId && Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null
  const readerQuery = useReadingPlanReader(planId)

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
  const modeLabel = readingPlanModeLabel(view.ordering_mode)
  const isStrict = view.ordering_mode === 'strict_sequential'
  const percent = progressPercent(view.progress.read_issues, view.progress.total_issues)
  const remaining = Math.max(view.progress.total_issues - view.progress.read_issues, 0)
  const continueIssue = view.available_now[0] ?? null
  const upcoming = view.lanes.flatMap((lane) =>
    lane.issues.filter((issue) => issue.availability === 'later'),
  )

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
            {isStrict
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
            onClick={() => navigate(`/continuity-plans/${planId}/edit`)}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-primary)]"
          >
            Edit plan
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
              <IssueRow key={issue.occurrence_id} issue={issue} />
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="blocked-next-heading" data-testid="blocked-next">
        <h2 id="blocked-next-heading" className="text-lg font-bold text-[var(--theme-text-primary)]">
          Blocked next
        </h2>
        <p className="mt-1 text-sm text-[var(--theme-text-muted)]">
          Next unread issues waiting on a hard prerequisite. Source reading order is not a blocker by
          itself.
        </p>
        {view.blocked_next.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--theme-text-dim)]">No hard blockers on the next unread issues in this plan.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {view.blocked_next.map((issue) => (
              <IssueRow key={issue.occurrence_id} issue={issue} />
            ))}
          </ul>
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
          <ul className="mt-3 space-y-2">
            {upcoming.map((issue) => (
              <IssueRow key={issue.occurrence_id} issue={issue} />
            ))}
          </ul>
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
            Where this plan’s order came from. A source reading order is not a hard reading block.
          </p>
          <ul className="mt-2 space-y-1 text-sm text-[var(--theme-text-primary)]">
            {view.sources.map((source) => (
              <li key={source.id}>
                {source.repository ? `${source.repository}: ` : ''}
                {source.source_path ?? source.raw_source_path}
                {source.revision_sha ? ` · ${source.revision_sha.slice(0, 8)}` : ''}
              </li>
            ))}
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
          <div className="mt-4 space-y-6">
            {view.lanes.map((lane) => (
              <section key={lane.id} aria-labelledby={`lane-${lane.id}-heading`} className="space-y-2">
                <h3 id={`lane-${lane.id}-heading`} className="text-base font-bold text-[var(--theme-text-primary)]">
                  {lane.name}
                </h3>
                {lane.issues.length === 0 ? (
                  <p className="text-sm text-[var(--theme-text-dim)]">This lane is empty.</p>
                ) : (
                  <ul className="space-y-2">
                    {lane.issues.map((issue) => (
                      <IssueRow key={issue.occurrence_id} issue={issue} />
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        )}
      </section>
    </section>
  )
}
