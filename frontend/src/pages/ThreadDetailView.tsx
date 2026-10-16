import { useEffect, useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams } from 'react-router-dom'
import Modal from '../components/Modal'
import LoadingSpinner from '../components/LoadingSpinner'
import { CrossoverTags } from '../components/CrossoverTags'
import { FormatSelect } from '../pages/QueuePage/FormatSelect'
import { useCrossoverGroups } from '../hooks/useCrossoverGroups'
import { useThread, useUpdateThread } from '../hooks/useThread'
import { useConnectedThreads } from '../hooks/useReaderContext'
import { useThreadIssuePages } from '../hooks/useThreadIssues'
import { useThreadIssuesEffectiveTags } from '../hooks/useTags'
import {
  applyEditedThreadToQueuePages,
  applyIssueReadSnapshotToCache,
  invalidateAfterDependencyChange,
} from '../query/cacheEffects'
import { getApiErrorDetail } from '../utils/apiError'
import type { ChangeEvent, FormEvent } from 'react'
import { getManualCreatorCreditList } from '../types'
import { DEFAULT_CREATE_STATE, type EditThreadData, type QueueFormState } from '../pages/QueuePage/types'
import DependencyBuilder from '../components/DependencyBuilder'
import Breadcrumbs from '../components/Breadcrumbs'
import { TagEditor } from '../components/Tags/TagEditor'
import { TagSection } from '../components/Tags/TagSection'
import { IssueTagRowChips } from '../components/Tags/IssueTagRowChips'
import { BulkTagToolbar } from '../components/Tags/BulkTagToolbar'
import { IssueToggleList, type IssueToggleListHandle } from '../pages/QueuePage/IssueToggleList'
import { IssueReadStatusButton } from './thread-detail/IssueReadStatusButton'
import type { IssueMutationSnapshot } from './thread-detail/issueMutationState'

export default function ThreadDetailView() {
  const { id } = useParams<{ id: string }>()
  const location = useLocation()
  const client = useQueryClient()
  const updateMutation = useUpdateThread()
  const activeThreadIdRef = useRef<number | null>(null)
  const editAutoOpenRef = useRef(false)
  const issueToggleListRef = useRef<IssueToggleListHandle>(null)

  // Normalize malformed ids (non-numeric, fractional, or non-positive) to null
  // so the view renders "Thread not found" instead of stalling on the loading
  // spinner: the thread/connected/issues hooks stay disabled with no error.
  const parsedThreadId = id ? Number(id) : NaN
  const threadId =
    Number.isInteger(parsedThreadId) && parsedThreadId > 0 ? parsedThreadId : null

  const { data: thread, error: threadError, refetch } = useThread(threadId)
  const {
    connectedThreads,
    isPending: connectedPending,
    isError: connectedError,
  } = useConnectedThreads(threadId)
  const {
    groupsByThreadId: crossoverGroupsByThreadId,
    isPending: crossoversPending,
    error: crossoversError,
  } = useCrossoverGroups(thread ? [thread.id] : [])

  const [isEditOpen, setIsEditOpen] = useState(false)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [issuesExpanded, setIssuesExpanded] = useState(false)
  const [isDependencyOpen, setIsDependencyOpen] = useState(false)
  // Tag editing (issue #3032): one editor serves the thread and any single
  // issue, while bulk-select mode enables multi-select bulk add/remove.
  const [tagEditorIssue, setTagEditorIssue] = useState<{
    id: number
    issue_number: string
  } | null>(null)
  const [bulkSelectMode, setBulkSelectMode] = useState(false)
  const [selectedIssueIds, setSelectedIssueIds] = useState<Set<number>>(new Set())
  const [bulkNotice, setBulkNotice] = useState<string | null>(null)

  const issuesQuery = useThreadIssuePages(threadId, { enabled: issuesExpanded })
  const issues = issuesQuery.issues
  // Row-level tag chips (issue #3422): one bulk read covers every visible
  // issue so rows render direct (solid) and inherited (dashed, read-only)
  // chips without opening an editor and without one request per issue.
  const rowTagsQuery = useThreadIssuesEffectiveTags(thread?.id ?? null, issuesExpanded)
  const rowTagsByIssueId = useMemo(() => {
    const entries = rowTagsQuery.data?.issues ?? []
    return new Map(entries.map((entry) => [entry.target_id, entry]))
  }, [rowTagsQuery.data])
  const issuesTotal = issuesQuery.totalCount
  const issuesLoading = issuesQuery.isPending
  const issuesError = issuesQuery.isError
  const issuesLoaded = issuesQuery.pages.length > 0
  const nextPageToken = issuesQuery.nextPageToken

  useEffect(() => {
    if (activeThreadIdRef.current !== threadId) {
      activeThreadIdRef.current = threadId
      setIssuesExpanded(false)
      setBulkSelectMode(false)
      setSelectedIssueIds(new Set())
      setBulkNotice(null)
      setTagEditorIssue(null)
    }
  }, [threadId])

  function handleToggleBulkSelect() {
    setBulkSelectMode((previous) => {
      if (previous) setSelectedIssueIds(new Set())
      return !previous
    })
  }

  function handleToggleIssueSelection(issueId: number) {
    setSelectedIssueIds((previous) => {
      const next = new Set(previous)
      if (next.has(issueId)) {
        next.delete(issueId)
      } else {
        next.add(issueId)
      }
      return next
    })
  }

  useEffect(() => {
    if (location.state?.openEditModal !== true || editAutoOpenRef.current || !thread) return
    editAutoOpenRef.current = true
    setEditForm({
      title: thread.title,
      format: thread.format,
      issuesRemaining: thread.issues_remaining,
      notes: thread.notes || '',
      issues: '',
      lastIssueRead: 0,
      manualCreatorCredits: getManualCreatorCreditList(thread),
    })
    setIsEditOpen(true)
  }, [location.state, thread])

  function handleToggleIssues() {
    setIssuesExpanded((prev) => !prev)
  }

  function handleLoadMore() {
    if (thread && thread.total_issues !== null && nextPageToken) {
      void issuesQuery.fetchNextPage()
    }
  }

  function handleIssueSnapshotChange(snapshot: IssueMutationSnapshot) {
    applyIssueReadSnapshotToCache(client, snapshot)
  }

  const handleEditSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const currentThread = thread!

    try {
      // First, flush any pending issue mutations (add, delete, reorder)
      if (issueToggleListRef.current && issueToggleListRef.current.hasPendingMutations()) {
        await issueToggleListRef.current.flush()
      }

      const updateData: EditThreadData = {
        title: editForm.title,
        format: editForm.format,
        notes: editForm.notes || null,
      }

      if (currentThread.total_issues === null) {
        updateData.issues_remaining = Number(editForm.issuesRemaining)
      }

      const updatedThread = await updateMutation.mutate({
        id: currentThread.id,
        data: updateData,
      })

      applyEditedThreadToQueuePages(client, updatedThread)
      setIsEditOpen(false)

      if (updatedThread.total_issues !== null && issuesLoaded) {
        await issuesQuery.refetch()
      }
    } catch (error) {
      console.error('Failed to update thread or flush issues:', error)
      // The error is already handled by the mutation's error boundary,
      // but we keep the console error for debugging
    }
  }

  const openEditModal = () => {
    const currentThread = thread!

    setEditForm({
      title: currentThread.title,
      format: currentThread.format,
      issuesRemaining: currentThread.issues_remaining,
      notes: currentThread.notes || '',
      issues: '',
      lastIssueRead: 0,
      manualCreatorCredits: getManualCreatorCreditList(currentThread),
    })
    setIsEditOpen(true)
  }

  const getProgressPercentage = (): string | null => {
    // `total_issues` is optional in the generated ThreadResponse; an absent
    // value and an explicit null both mean "no known total".
    const totalIssues = thread?.total_issues ?? null
    if (thread && totalIssues !== null) {
      const readCount = totalIssues - thread.issues_remaining
      const percentage = Math.round((readCount / totalIssues) * 100)
      return `${percentage}%`
    }
    return null
  }

  const getIssuesReadCount = (): string | null => {
    const totalIssues = thread?.total_issues ?? null
    if (thread && totalIssues !== null) {
      const readCount = totalIssues - thread.issues_remaining
      return `${readCount} of ${totalIssues} issues read`
    }
    return null
  }

  if (threadId === null || !thread) {
    if (threadId !== null && !thread && !threadError) {
      return <LoadingSpinner fullScreen />
    }

    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="px-2">
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase">
            Thread Details
          </h1>
          <p className="text-base font-semibold text-stone-500">
            View thread information
          </p>
        </header>
        <div className="text-center text-stone-500">
          {threadError ? getApiErrorDetail(threadError) : 'Thread not found'}
        </div>
      </div>
    )
  }

  const isMigrated = thread.total_issues !== null
  const progressPercentage = getProgressPercentage()
  const issuesReadCount = getIssuesReadCount()
  const crossoverGroups = crossoverGroupsByThreadId[thread.id] ?? []

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex justify-between items-start px-2 gap-2 md:gap-4">
        <div className="flex-1 min-w-0">
          <Breadcrumbs items={[{ label: 'Queue', to: '/queue' }, { label: 'Thread' }]} />
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase truncate">
            {thread.title}
          </h1>
          <p className="text-sm font-medium text-stone-500">
            {thread.format}
          </p>
        </div>
        <button
          type="button"
          onClick={openEditModal}
          className="h-9 md:h-12 px-4 md:px-5 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] whitespace-nowrap hover:text-[var(--theme-text-primary)] transition-colors shrink-0"
        >
          Edit
        </button>
      </header>

      <div className="space-y-4 md:space-y-6">
        {progressPercentage && (
          <div className="surface-panel p-3 md:p-4 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">
                Reading Progress
              </span>
              <span className="text-sm font-black text-amber-400">{progressPercentage}</span>
            </div>
            <div className="w-full bg-white/10 rounded-full h-2 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all duration-300"
                style={{ width: progressPercentage }}
              />
            </div>
            <p className="text-xs text-stone-400">{issuesReadCount}</p>
          </div>
        )}

        {thread.notes && (
          <div className="surface-panel p-3 md:p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">
              Notes
            </span>
            <p className="text-sm text-stone-300 whitespace-pre-wrap">{thread.notes}</p>
          </div>
        )}

        <div className="surface-panel p-3 md:p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">
            Dependencies
          </span>
          {connectedError && (
            <p className="text-xs text-red-400" role="alert">Unable to load dependencies.</p>
          )}
          {!connectedError && connectedPending && (
            <p className="text-xs text-stone-500">Loading dependencies...</p>
          )}
          {!connectedError && !connectedPending && connectedThreads.length === 0 && (
            <p className="text-xs text-stone-500">No series dependencies</p>
          )}
          {!connectedError && !connectedPending && connectedThreads.length > 0 && (
            <div className="space-y-3">
              {(() => {
                // A circular connection both blocks and is blocked by this
                // series (#3239). Listing it under "Blocked by" and "Blocking"
                // simultaneously is exactly the impossible reading order the
                // report describes, so it is presented once in its own region
                // and excluded from both directional lists.
                const circular = connectedThreads.filter((t) => t.is_circular)
                const oneWay = connectedThreads.filter((t) => !t.is_circular)
                const blockedBy = oneWay.filter((t) => t.connection_type.includes('blocked_by'))
                const blocking = oneWay.filter((t) => t.connection_type.includes('blocks'))

                return (
                  <>
                    {circular.length > 0 && (
                      <div className="space-y-1">
                        <h3 className="text-base font-bold text-[var(--theme-warning)]">⚠️ Circular Dependencies</h3>
                        <p className="text-xs text-[var(--theme-text-muted)]">
                          Each series below both blocks and is blocked by this series — an impossible
                          reading order until the dependency direction is corrected. They are listed
                          here once instead of under both directions.
                        </p>
                        {circular.map((t) => (
                          <Link
                            key={`circular-${t.thread_id}`}
                            to={`/thread/${t.thread_id}`}
                            className="flex items-center gap-2 p-2 rounded-lg border border-[var(--theme-warning)]/40 bg-[var(--theme-warning)]/10 hover:bg-[var(--theme-warning)]/20 transition-colors"
                            aria-label={`Open ${t.title} (circular dependency)`}
                          >
                            <span aria-hidden="true">⚠️</span>
                            <span className="text-sm text-[var(--theme-warning)] truncate">
                              {t.title}{t.issue_number ? `: #${t.issue_number}` : ''}
                            </span>
                          </Link>
                        ))}
                      </div>
                    )}

                    <div className="space-y-1">
                      <h3 className="text-base font-bold text-stone-400">Blocked by</h3>
                      {blockedBy.length === 0 && <p className="text-xs text-stone-500">Nothing blocks this series</p>}
                      {blockedBy.map((t) => (
                        <Link
                          key={`${t.dependency_id}-blocked-by`}
                          to={`/thread/${t.thread_id}`}
                          className="flex items-center gap-2 p-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 transition-colors"
                          aria-label={`Open ${t.title}`}
                        >
                          <span aria-hidden="true">🔒</span>
                          <span className="text-sm text-stone-300 truncate">
                            {t.title}{t.issue_number ? `: #${t.issue_number}` : ''}
                          </span>
                        </Link>
                      ))}
                    </div>
                    <div className="space-y-1">
                      <h3 className="text-base font-bold text-stone-400">Blocking</h3>
                      {blocking.length === 0 && <p className="text-xs text-stone-500">This series blocks nothing</p>}
                      {blocking.map((t) => (
                        <Link
                          key={`${t.dependency_id}-blocking`}
                          to={`/thread/${t.thread_id}`}
                          className="flex items-center gap-2 p-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 transition-colors"
                          aria-label={`Open ${t.title}`}
                        >
                          <span aria-hidden="true">🔓</span>
                          <span className="text-sm text-stone-300 truncate">
                            {t.title}{t.issue_number ? `: #${t.issue_number}` : ''}
                          </span>
                        </Link>
                      ))}
                    </div>
                  </>
                )
              })()}
            </div>
          )}
        </div>

        <div className="surface-panel p-3 md:p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">
            Crossovers
          </span>
          {crossoversPending && <p className="text-xs text-stone-500">Loading crossovers...</p>}
          {!crossoversPending && crossoversError && (
            <p className="text-xs text-red-400">Unable to load crossover memberships.</p>
          )}
          {!crossoversPending && !crossoversError && crossoverGroups.length === 0 && (
            <p className="text-xs text-stone-500">No crossover memberships</p>
          )}
          {!crossoversPending && !crossoversError && (
            <CrossoverTags groups={crossoverGroups} label={`${thread.title} crossovers`} />
          )}
        </div>

        <div className="surface-panel p-3 md:p-4 space-y-2">
          <TagSection
            targetType="Thread"
            targetId={thread.id}
            targetLabel={thread.title}
          />
        </div>

        {isMigrated && (
          <div className="surface-panel p-3 md:p-4 space-y-3">
            <div className="flex justify-between items-center gap-2">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">
                Issues ({issuesTotal > 0 ? issuesTotal : (thread.total_issues ?? issues.length)})
              </span>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={handleToggleBulkSelect}
                  aria-pressed={bulkSelectMode}
                  className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300"
                >
                  {bulkSelectMode ? 'Done' : 'Select'}
                </button>
                <button
                  type="button"
                  onClick={handleToggleIssues}
                  className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300"
                >
                  {issuesExpanded ? 'Collapse' : 'Expand'}
                </button>
              </div>
            </div>

            {!issuesExpanded && (
              <p className="text-xs text-stone-500">
                {thread.next_unread_issue_number
                  ? `Next up: #${thread.next_unread_issue_number}`
                  : 'All issues read'}
              </p>
            )}

              {issuesExpanded && (
                <div className="space-y-2 mt-3">
                {bulkNotice && (
                  <p role="status" className="text-xs text-stone-400">
                    {bulkNotice}
                  </p>
                )}
                {bulkSelectMode && (
                  <BulkTagToolbar
                    selectedIds={[...selectedIssueIds]}
                    onClearSelection={() => setSelectedIssueIds(new Set())}
                    onDone={(summary) => setBulkNotice(summary)}
                  />
                )}
                {issuesLoading && issues.length === 0 && (
                  <p className="text-xs text-stone-500">Loading issues...</p>
                )}

                {issuesError && !issuesLoading && (
                  <div className="space-y-2">
                    <p className="text-xs text-red-400">Failed to load issues</p>
                    <button
                      type="button"
                      onClick={() => {
                        void issuesQuery.refetch()
                      }}
                      className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300"
                    >
                      Retry
                    </button>
                  </div>
                )}

                {issuesLoaded && !issuesLoading && !issuesError && issues.length === 0 && (
                  <p className="text-xs text-stone-500">No issues yet</p>
                )}

                {issuesLoaded && issues.length > 0 && (
                  <div className="space-y-2">
                    {issues.map((issue) => {
                      const rowTags = rowTagsByIssueId.get(issue.id)
                      return (
                        <div
                          key={issue.id}
                          className={`space-y-1.5 p-2 rounded-lg border ${
                            issue.status === 'read'
                              ? 'bg-green-500/10 border-green-500/20'
                              : 'bg-white/5 border-white/10'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <span className="flex min-w-0 items-center gap-2">
                              {bulkSelectMode && (
                                <input
                                  type="checkbox"
                                  checked={selectedIssueIds.has(issue.id)}
                                  onChange={() => handleToggleIssueSelection(issue.id)}
                                  aria-label={`Select issue #${issue.issue_number}`}
                                  className="h-4 w-4 shrink-0 accent-amber-400"
                                />
                              )}
                              <span className="text-sm font-medium text-stone-300">
                                #{issue.issue_number}
                              </span>
                            </span>
                            <div className="flex items-center gap-3">
                              <button
                                type="button"
                                onClick={() =>
                                  setTagEditorIssue({
                                    id: issue.id,
                                    issue_number: issue.issue_number,
                                  })
                                }
                                aria-label={`Edit tags for issue #${issue.issue_number}`}
                                title={`Edit tags for issue #${issue.issue_number}`}
                                className="text-xs font-black uppercase tracking-widest text-stone-500 hover:text-amber-300"
                              >
                                Tags
                              </button>
                              <span className="text-xs font-black uppercase tracking-widest">
                                {issue.status === 'read' ? (
                                  <span className="text-green-400">Read</span>
                                ) : (
                                  <span className="text-stone-500">Unread</span>
                                )}
                              </span>
                              <IssueReadStatusButton
                                issue={issue}
                                snapshot={{ issues, thread }}
                                onSnapshotChange={handleIssueSnapshotChange}
                              />
                            </div>
                          </div>
                          {rowTags && (
                            <IssueTagRowChips
                              data={rowTags}
                              issueNumber={issue.issue_number}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}

                {nextPageToken && !issuesLoading && (
                  <button
                    type="button"
                    onClick={handleLoadMore}
                    className="w-full py-2 rounded-lg border border-white/10 text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300 hover:border-white/20"
                  >
                    Load more
                  </button>
                )}

                {issuesLoading && issues.length > 0 && (
                  <p className="text-xs text-stone-500">Loading more...</p>
                )}
              </div>
            )}
          </div>
        )}

        {!isMigrated && (
          <div className="surface-panel p-3 md:p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">
              Issues Remaining
            </span>
            <p className="text-sm text-stone-300">{thread.issues_remaining} issues</p>
          </div>
        )}

        {thread.status === 'active' && (
          <div className="surface-panel p-3 md:p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">
              Queue Position
            </span>
            <p className="text-sm text-stone-300">Position #{thread.queue_position}</p>
          </div>
        )}

        <div className="surface-panel p-3 md:p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">
            Status
          </span>
          <p className="text-sm font-black uppercase">{thread.status}</p>
        </div>
      </div>

      <Modal
        isOpen={isEditOpen}
        title="Edit Series"
        onClose={() => {
          setIsEditOpen(false)
        }}
        overlayClassName="edit-modal__overlay"
      >
        <div className="space-y-4">
          <form id="edit-thread-form" className="space-y-4" onSubmit={handleEditSubmit}>
            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-500">
                Title
              </label>
              <input
                value={editForm.title}
                onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                className="w-full rounded-xl px-3 py-2 text-sm form-control"
                required
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-500">
                Format
              </label>
              <FormatSelect
                value={editForm.format}
                onChange={(value) => setEditForm({ ...editForm, format: value })}
                required
              />
            </div>

            {thread.total_issues === null && (
              <div className="space-y-2">
                <label className="text-sm font-medium text-stone-500">
                  Issues Remaining
                </label>
                <input
                  type="number"
                  min="0"
                  value={editForm.issuesRemaining}
                  onChange={(event: ChangeEvent<HTMLInputElement>) =>
                    setEditForm({
                      ...editForm,
                      issuesRemaining: Number.parseInt(event.target.value, 10) || 0,
                    })
                  }
                  className="w-full rounded-xl px-3 py-2 text-sm form-control"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-sm font-medium text-stone-500">
                Notes
              </label>
              <textarea
                value={editForm.notes}
                onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
                className="w-full rounded-xl px-3 py-2 text-sm form-control min-h-[80px]"
              />
            </div>
          </form>

          {thread.total_issues !== null && (
            <IssueToggleList
              ref={issueToggleListRef}
              threadId={thread.id}
              onOpenDependencies={() => setIsDependencyOpen(true)}
              onIssueChanged={() => {
                // Refetch thread data to update STATUS display after issue mutations
                refetch()
              }}
              deferred={true}
            />
          )}

          <button
            type="submit"
            form="edit-thread-form"
            disabled={updateMutation.isPending}
            className="w-full py-3 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-60"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </Modal>

      <DependencyBuilder
        thread={thread}
        isOpen={isDependencyOpen}
        onClose={() => setIsDependencyOpen(false)}
        onChanged={() => {
          if (thread) {
            void invalidateAfterDependencyChange(client, thread.id)
          }
        }}
      />

      {tagEditorIssue && (
        <TagEditor
          targetType="Issue"
          targetId={tagEditorIssue.id}
          targetLabel={`#${tagEditorIssue.issue_number}`}
          isOpen={tagEditorIssue !== null}
          onClose={() => setTagEditorIssue(null)}
        />
      )}
    </div>
  )
}