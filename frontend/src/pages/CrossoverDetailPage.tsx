import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { dependencyGroupsApi, type DependencyGroup, type DependencyGroupMember, type DependencyGroupSummary } from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import { continuityReadinessApi, type ContinuityReadinessResponse, type ContinuityBlocker } from '../services/api-continuity-readiness'
import { getApiErrorDetail } from '../utils/apiError'
import type { Thread, Issue } from '../types'

interface CrossoverMember {
  membership: DependencyGroupMember
  thread: Thread | null
  issue: Issue | null
  otherCrossovers: string[]
}

interface BlockedMember {
  membershipId: number
  threadTitle: string
  issueNumber: string
  blockers: ContinuityBlocker[]
}

export default function CrossoverDetailPage() {
  const { group } = useParams<{ group: string }>()
  const groupId = parseInt(group ?? '', 10)

  const [crossover, setCrossover] = useState<DependencyGroup | null>(null)
  const [members, setMembers] = useState<CrossoverMember[]>([])
  const [readiness, setReadiness] = useState<ContinuityReadinessResponse | null>(null)
  const [linkedPlans, setLinkedPlans] = useState<DependencyGroupSummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadCrossover = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const groupData = await dependencyGroupsApi.get(groupId)
      setCrossover(groupData)

      const enrichedMembers: CrossoverMember[] = []

      for (const membership of groupData.memberships) {
        let thread: Thread | null = null
        let issue: Issue | null = null
        let otherCrossovers: string[] = []

        if (membership.thread_id) {
          thread = await threadsApi.get(membership.thread_id)
          const threadGroups = await dependencyGroupsApi.listForThread(membership.thread_id)
          otherCrossovers = threadGroups
            .filter((g) => g.id !== groupId)
            .map((g) => g.name)
        } else if (membership.issue_id) {
          issue = await issuesApi.get(membership.issue_id)
          thread = await threadsApi.get(issue.thread_id)
          const threadGroups = await dependencyGroupsApi.listForThread(issue.thread_id)
          otherCrossovers = threadGroups
            .filter((g) => g.id !== groupId)
            .map((g) => g.name)
        }

        enrichedMembers.push({
          membership,
          thread,
          issue,
          otherCrossovers,
        })
      }

      setMembers(enrichedMembers)

      const readinessData = await continuityReadinessApi.evaluate('crossover', groupId)
      setReadiness(readinessData)

      const plans = await dependencyGroupsApi.plansForGroup(groupId)
      setLinkedPlans(plans)
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
      <div className="p-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-stone-400">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-stone-400 mt-8">
          <div className="flex items-center gap-2 justify-center">
            <div className="text-sm font-semibold text-stone-500">Loading crossover…</div>
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-stone-400">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-red-500 mt-8">
          <p className="text-lg font-medium">Error loading crossover</p>
          <p className="mt-1 text-sm">{error}</p>
          <button
            onClick={loadCrossover}
            className="mt-4 rounded-lg bg-amber-500 px-4 py-2 font-bold text-stone-950"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!crossover) {
    return (
      <div className="p-6">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
          <Link to="/crossovers" className="text-sm text-stone-400">
            ← Back to Crossovers
          </Link>
        </div>
        <div className="text-center text-red-500 mt-8">
          <p className="text-lg font-medium">Crossover not found</p>
          <Link
            to="/crossovers"
            className="mt-4 inline-block rounded-lg bg-amber-500 px-4 py-2 font-bold text-stone-950"
          >
            Back to Crossovers
          </Link>
        </div>
      </div>
    )
  }

  const sortedMembers = [...members].sort((a, b) => {
    const posA = a.issue?.position ?? 0
    const posB = b.issue?.position ?? 0
    return posA - posB
  })

  const readCount = sortedMembers.filter(m => m.issue?.status === 'read').length
  const totalCount = sortedMembers.filter(m => m.issue).length
  const nextUnread = sortedMembers.find(m => m.issue?.status === 'unread')

  const blockedMembers = readiness?.blockers.flatMap(blocker => {
    const member = members.find(m => 
      (blocker.source_type === 'thread' && m.membership.thread_id === blocker.source_id) ||
      (blocker.source_type === 'issue' && m.membership.issue_id === blocker.source_id)
    )
    if (!member) return []
    return [{
      membershipId: member.membership.id,
      threadTitle: member.thread?.title ?? 'Unknown Series',
      issueNumber: member.issue?.issue_number ?? '?',
      blockers: [blocker],
    }]
  }) ?? []

  const blockedMemberMap = new Map(blockedMembers.map(b => [b.membershipId, b]))

  return (
    <div className="space-y-6 md:space-y-8 px-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-stone-100">Crossover Detail</h1>
        <Link to="/crossovers" className="text-sm text-stone-400">
          ← Back to Crossovers
        </Link>
      </div>

      <div className="rounded-2xl border border-stone-700 bg-stone-900/50 p-4 md:p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h2 className="text-xl font-bold text-stone-100">{crossover.name}</h2>
            <p className="text-sm text-stone-500">ID: {crossover.id} • {crossover.memberships.length} member{crossover.memberships.length !== 1 ? 's' : ''}</p>
          </div>
          <div className="flex gap-2">
            <Link
              to={'/threads/' + (nextUnread?.thread?.id ?? sortedMembers[0]?.thread?.id)}
              className="rounded-lg bg-amber-500 px-4 py-2 font-bold text-stone-950 text-sm"
            >
              Continue Reading
            </Link>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="rounded-xl border border-stone-700 bg-stone-950/50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Members</p>
            <p className="mt-1 text-2xl font-bold text-stone-100">{members.length}</p>
          </div>
          <div className="rounded-xl border border-stone-700 bg-stone-950/50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Issues Tracked</p>
            <p className="mt-1 text-2xl font-bold text-stone-100">{totalCount}</p>
          </div>
          <div className="rounded-xl border border-stone-700 bg-stone-950/50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Read</p>
            <p className="mt-1 text-2xl font-bold text-emerald-400">{readCount}</p>
          </div>
          <div className="rounded-xl border border-stone-700 bg-stone-950/50 p-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-stone-500">Progress</p>
            <p className="mt-1 text-2xl font-bold text-stone-100">
              {totalCount > 0 ? Math.round((readCount / totalCount) * 100) : 0}%
            </p>
          </div>
        </div>

        {readiness && (
          <div className={'rounded-xl p-4 mb-6 ' + (readiness.is_readable ? 'border-emerald-800 bg-emerald-950/30' : 'border-red-800 bg-red-950/30')}>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className={'rounded-full px-2 py-0.5 text-xs font-bold ' + (readiness.is_readable ? 'bg-emerald-500 text-stone-950' : 'bg-red-500 text-stone-100')}>
                  {readiness.is_readable ? 'Readable' : 'Blocked'}
                </span>
                <span className="text-sm text-stone-300">
                  {readiness.is_readable
                    ? 'This crossover is ready to read.'
                    : readiness.blockers.length + ' continuity rule' + (readiness.blockers.length !== 1 ? 's' : '') + ' blocking.'}
                </span>
              </div>
              {readiness.evaluated_issue_id && (
                <span className="text-xs text-stone-500">Evaluated issue: {readiness.evaluated_issue_id}</span>
              )}
            </div>
            {!readiness.is_readable && readiness.blockers.length > 0 && (
              <details className="mt-3">
                <summary className="cursor-pointer text-sm text-amber-400 hover:text-amber-300">Show blocking details</summary>
                <div className="mt-2 space-y-2 text-sm">
                  {readiness.blockers.map((blocker, index) => (
                    <div key={index} className="rounded-lg bg-stone-900/50 p-3 border border-stone-700">
                      <div className="flex gap-2">
                        <span className="font-medium text-stone-300">{blocker.source_label}</span>
                        <span className="text-stone-500">({blocker.satisfaction_type})</span>
                      </div>
                      {blocker.unread_issue_details.length > 0 && (
                        <ul className="mt-1 ml-4 list-disc space-y-1 text-stone-400">
                          {blocker.unread_issue_details.map((detail, i) => (
                            <li key={i}>Unread: {detail.label} (Issue {detail.issue_id})</li>
                          ))}
                        </ul>
                      )}
                      {blocker.note && (
                        <p className="mt-1 text-stone-500">{blocker.note}</p>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}

        {nextUnread && (
          <div className="rounded-xl border border-amber-800 bg-amber-950/30 p-4 mb-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="rounded-full bg-amber-500 px-2 py-0.5 text-xs font-bold text-stone-950">Next Up</span>
                <div>
                  <p className="font-medium text-stone-100">
                    {nextUnread.thread?.title ?? 'Unknown Series'}
                  </p>
                  <p className="text-sm text-stone-400">
                    Issue {nextUnread.issue?.issue_number ?? '?'}
                    {nextUnread.issue?.position && ' • Position ' + nextUnread.issue.position}
                  </p>
                </div>
              </div>
              <Link
                to={'/threads/' + nextUnread.thread?.id}
                className="rounded-lg bg-amber-500 px-3 py-1.5 font-bold text-stone-950 text-sm"
              >
                Read Now
              </Link>
            </div>
          </div>
        )}

        <div className="border-t border-stone-800 pt-6">
          <h3 className="text-lg font-bold text-stone-100 mb-4">Reading Order</h3>
          {sortedMembers.length === 0 ? (
            <p className="text-stone-500 text-center py-8">No members in this crossover yet.</p>
          ) : (
            <div className="space-y-2 max-h-96 overflow-y-auto">
              {sortedMembers.map((member, index) => {
                const isRead = member.issue?.status === 'read'
                const position = member.issue?.position ?? index + 1
                const threadTitle = member.thread?.title ?? 'Unknown Series'
                const issueNumber = member.issue?.issue_number ?? '?'
                const blockedInfo = blockedMemberMap.get(member.membership.id)

                return (
                  <div
                    key={member.membership.id}
                    data-testid="crossover-member-row"
                    className={'flex items-center gap-3 rounded-lg p-3 transition-colors ' + (
                      blockedInfo
                        ? 'bg-red-950/20 border border-red-800/50'
                        : isRead
                        ? 'bg-stone-800/50 border border-stone-700'
                        : 'bg-amber-950/20 border border-amber-800/50'
                    )}
                  >
                    <span className="w-8 text-center text-sm font-mono font-bold text-stone-400">
                      {position}.
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className={`truncate font-medium ${isRead ? 'text-stone-300 line-through' : 'text-stone-100'}`}>
                        {threadTitle}
                        {blockedInfo && (
                          <span className="ml-2 rounded px-1.5 py-0.5 text-xs font-medium bg-red-950/50 text-red-400">
                            Blocked
                          </span>
                        )}
                      </p>
                      <p className={`truncate text-sm ${isRead ? 'text-stone-500' : 'text-stone-400'}`}>
                        Issue {issueNumber}
                        {member.otherCrossovers.length > 0 && (
                          <>
                            {' • '}
                            <span className="text-violet-400">
                              Also in: {member.otherCrossovers.join(', ')}
                            </span>
                          </>
                        )}
                      </p>
                      {blockedInfo && (
                        <details className="mt-1">
                          <summary className="cursor-pointer text-xs text-red-400 hover:text-red-300">Blocking reasons</summary>
                          <ul className="mt-1 ml-4 list-disc space-y-0.5 text-xs text-stone-500">
                            {blockedInfo.blockers.map((blocker, i) => (
                              <li key={i}>
                                {blocker.source_label} ({blocker.satisfaction_type})
                                {blocker.unread_issue_details.length > 0 && (
                                  <span className="text-stone-400">
                                    {' — '}
                                    {blocker.unread_issue_details.map(d => d.label).join(', ')}
                                  </span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          isRead
                            ? 'bg-emerald-950/50 text-emerald-400'
                            : 'bg-amber-950/50 text-amber-400'
                        }`}
                      >
                        {isRead ? 'Read' : 'Unread'}
                      </span>
                      {member.thread && (
                        <Link
                          to={`/threads/${member.thread.id}`}
                          className="text-sm text-amber-400 hover:text-amber-500"
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

          <div className="mt-6 pt-6 border-t border-stone-800">
            <h3 className="text-lg font-bold text-stone-100 mb-4">Actions</h3>
            <div className="flex flex-wrap gap-3">
              <Link
                to="/crossovers"
                className="rounded-lg border border-stone-600 bg-stone-800/50 px-4 py-2 text-sm font-medium text-stone-200 hover:bg-stone-700"
              >
                ← Back to Crossovers
              </Link>
              {linkedPlans.length > 0 && linkedPlans.map((plan) => (
                <Link
                  key={plan.id}
                  to={`/continuity-plans/${plan.id}`}
                  className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-stone-950"
                >
                  Reading Plan: {plan.name}
                </Link>
              ))}
              {sortedMembers.length > 0 && sortedMembers[0].thread && (
                <Link
                  to={`/threads/${sortedMembers[0].thread.id}`}
                  className="rounded-lg bg-amber-500 px-4 py-2 text-sm font-bold text-stone-950"
                >
                  View First Series
                </Link>
              )}
              <Link
                to={`/crossovers`}
                className="rounded-lg border border-stone-600 bg-stone-800/50 px-4 py-2 text-sm font-medium text-stone-200 hover:bg-stone-700"
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
    </div>
  )
}
