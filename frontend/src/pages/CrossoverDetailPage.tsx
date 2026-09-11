import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { dependencyGroupsApi, type DependencyGroup, type DependencyGroupMember, type DependencyGroupSummary } from '../services/api-dependency-groups'
import { getApiErrorDetail } from '../utils/apiError'
import type { Thread, Issue } from '../types'

interface CrossoverMember {
  membership: DependencyGroupMember
  thread: Thread | null
  issue: Issue | null
  other_crossovers: string[]
}


export default function CrossoverDetailPage() {
  const { group } = useParams<{ group: string }>()
  const groupId = parseInt(group ?? '', 10)

  const [crossover, setCrossover] = useState<DependencyGroup | null>(null)
  const [members, setMembers] = useState<CrossoverMember[]>([])
  const [linkedPlans, setLinkedPlans] = useState<DependencyGroupSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadCrossover = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const detail = await dependencyGroupsApi.getDetail(groupId)
      setCrossover({
        id: detail.id,
        name: detail.name,
        created_at: detail.created_at,
        memberships: detail.memberships.map((m) => m.membership),
      })
      setMembers(
        detail.memberships.map((m) => ({
          membership: m.membership,
          thread: m.thread,
          issue: m.issue,
          other_crossovers: m.other_crossovers,
        })),
      )
      setLinkedPlans(detail.linked_plans ?? [])
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setIsLoading(false)
    }
  }, [groupId])

  useEffect(() => {
    loadCrossover()
  }, [loadCrossover])

  if (isLoading) {
    return (
      <div className="px-4">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-[var(--theme-text-muted)]">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-[var(--theme-text-muted)] mt-8">
          <div className="flex items-center gap-2 justify-center">
            <div className="text-sm font-semibold text-[var(--theme-text-dim)]">Loading crossover…</div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="px-4">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-[var(--theme-text-muted)]">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-[var(--theme-danger)] mt-8">
          <p className="text-lg font-medium">Error loading crossover</p>
          <p className="mt-1 text-sm">{error}</p>
          <button
            onClick={loadCrossover}
            className="mt-4 rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 font-bold text-[var(--theme-text-primary)]"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!crossover) {
    return (
      <div className="px-4">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-[var(--theme-text-muted)]">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-[var(--theme-danger)] mt-8">
          <p className="text-lg font-medium">Crossover not found</p>
          <Link
            to="/crossovers"
            className="mt-4 inline-block rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 font-bold text-[var(--theme-text-primary)]"
          >
            Back to Crossovers
          </Link>
        </div>
      </div>
    )
  }

  const sortedMembers = [...members].sort((a, b) => {
    const orderA = a.membership?.sequence_order ?? 0
    const orderB = b.membership?.sequence_order ?? 0
    return orderA - orderB
  })

  const readCount = sortedMembers.filter(m => m.issue?.status === 'read').length
  const totalCount = sortedMembers.filter(m => m.issue).length
  const nextUnread = sortedMembers.find(m => m.issue?.status === 'unread')


  return (
    <div className="space-y-6 md:space-y-8 px-4 pb-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-[var(--theme-text-primary)]">Crossover Detail</h1>
        <Link to="/crossovers" className="text-sm text-[var(--theme-text-muted)]">
          ← Back to Crossovers
        </Link>
      </div>

      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-[var(--theme-text-primary)]">{crossover.name}</h2>
          <p className="text-sm text-[var(--theme-text-dim)]">ID: {crossover.id} • {crossover.memberships.length} member{crossover.memberships.length !== 1 ? 's' : ''}</p>
        </div>
        <Link
          to={'/threads/' + (nextUnread?.thread?.id ?? sortedMembers[0]?.thread?.id)}
          className="inline-flex min-h-11 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-primary-action-hover)] transition-colors"
        >
          Continue Reading
        </Link>
      </div>

      <div className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-3 sm:px-6 sm:py-4">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4 sm:gap-y-0 sm:divide-x sm:divide-[var(--theme-border)]">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Members</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">{members.length}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Issues Tracked</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">{totalCount}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Read</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-continuity-accent)]">{readCount}</dd>
          </div>
          <div className="sm:pl-6">
            <dt className="text-xs font-semibold uppercase tracking-wide text-[var(--theme-text-muted)]">Progress</dt>
            <dd className="mt-1 text-2xl font-bold text-[var(--theme-text-primary)]">
              {totalCount > 0 ? Math.round((readCount / totalCount) * 100) : 0}%
            </dd>
          </div>
        </dl>
      </div>

      {nextUnread && (
        <div className="rounded-xl border border-[var(--theme-continuity-accent)]/40 bg-[var(--theme-continuity-accent)]/10 p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <span className="shrink-0 rounded-full px-2 py-0.5 text-xs font-bold text-[var(--theme-continuity-accent)]">Next Up</span>
              <div className="min-w-0">
                <p className="font-medium text-[var(--theme-text-primary)] truncate">
                  {nextUnread.thread?.title ?? 'Unknown Series'}
                </p>
                <p className="text-sm text-[var(--theme-text-muted)]">
                  Issue {nextUnread.issue?.issue_number ?? '?'}
                  {nextUnread.membership?.sequence_order && ' • Position ' + nextUnread.membership.sequence_order}
                </p>
              </div>
            </div>
            <Link
              to={'/threads/' + nextUnread.thread?.id}
              className="shrink-0 inline-flex min-h-11 items-center justify-center rounded-lg bg-[var(--theme-primary-action)] px-3 py-1.5 text-sm font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-primary-action-hover)] transition-colors"
            >
              Read Now
            </Link>
          </div>
        </div>
      )}

      <div className="border-t border-[var(--theme-border)] pt-6">
        <h3 className="text-lg font-bold text-[var(--theme-text-primary)] mb-4">Reading Order</h3>
        {sortedMembers.length === 0 ? (
          <p className="text-[var(--theme-text-muted)] text-center py-8">No members in this crossover yet.</p>
        ) : (
          <div className="space-y-2" data-testid="crossover-reading-order">
              {sortedMembers.map((member, index) => {
                const isRead = member.issue?.status === 'read'
                const position = member.membership?.sequence_order ?? index + 1
                const threadTitle = member.thread?.title ?? 'Unknown Series'
                const issueNumber = member.issue?.issue_number ?? '?'

              return (
                <div
                  key={member.membership.id}
                  data-testid="crossover-member-row"
                  className={'flex items-center gap-3 rounded-lg p-3 transition-colors ' + (isRead
                    ? 'bg-[var(--theme-bg-panel)] border border-[var(--theme-border)]'
                    : 'bg-[var(--theme-continuity-accent)]/10 border border-[var(--theme-continuity-accent)]/30'
                  )}
                >
                  <span className="w-8 shrink-0 text-center text-sm font-mono font-bold text-[var(--theme-text-muted)]">
                    {position}.
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className={`truncate font-medium ${isRead ? 'text-[var(--theme-text-muted)] line-through' : 'text-[var(--theme-text-primary)]'}`}>
                      {threadTitle}
                    </p>
                    <p className={`truncate text-sm ${isRead ? 'text-[var(--theme-text-dim)]' : 'text-[var(--theme-text-muted)]'}`}>
                      Issue {issueNumber}
                      {member.other_crossovers.length > 0 && (
                        <>
                          {' • '}
                          <span className="text-[var(--theme-continuity-accent)]">
                            Also in: {member.other_crossovers.join(', ')}
                          </span>
                        </>
                      )}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span
                      className={'rounded-full px-2 py-0.5 text-xs font-medium bg-[var(--theme-continuity-accent)]/15 text-[var(--theme-continuity-accent)]'}
                    >
                      {isRead ? 'Read' : 'Unread'}
                    </span>
                    {member.thread && (
                      <Link
                        to={`/threads/${member.thread.id}`}
                        className="text-sm text-[var(--theme-continuity-accent)] hover:text-[var(--theme-text-primary)]"
                      >
                        Open
                      </Link>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        <div className="mt-6 pt-6 border-t border-[var(--theme-border)]">
          <h3 className="text-lg font-bold text-[var(--theme-text-primary)] mb-4">Actions</h3>
          <div className="flex flex-wrap gap-3">
            <Link
              to="/crossovers"
              className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-2 text-sm font-medium text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
            >
              ← Back to Crossovers
            </Link>
            {linkedPlans.length > 0 && linkedPlans.map((plan) => (
              <Link
                key={plan.id}
                to={`/continuity-plans/${plan.id}`}
                className="rounded-lg bg-[var(--theme-continuity-accent)] px-4 py-2 text-sm font-bold text-[var(--theme-text-primary)]"
              >
                Reading Plan: {plan.name}
              </Link>
            ))}
            {sortedMembers.length > 0 && sortedMembers[0].thread && (
              <Link
                to={`/threads/${sortedMembers[0].thread.id}`}
                className="rounded-lg bg-[var(--theme-primary-action)] px-4 py-2 text-sm font-bold text-[var(--theme-text-primary)]"
              >
                View First Series
              </Link>
            )}
            <Link
              to={`/crossovers`}
              className="rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 py-2 text-sm font-medium text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
              onClick={(e) => {
                e.preventDefault()
                window.history.back()
              }}
            >
              Back
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
