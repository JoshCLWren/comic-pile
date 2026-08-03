import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Modal from '../components/Modal'
import LoadingSpinner from '../components/LoadingSpinner'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import type { Thread, Issue } from '../types'
import { FormatSelect } from '../pages/QueuePage/FormatSelect'
import { useUpdateThread } from '../hooks/useThread'
import { getApiErrorDetail } from '../utils/apiError'
import type { ChangeEvent, FormEvent } from 'react'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'
import { IssueReadStatusButton } from './thread-detail/IssueReadStatusButton'
import type { IssueMutationSnapshot } from './thread-detail/issueMutationState'

export default function ThreadDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const updateMutation = useUpdateThread()
  const activeThreadIdRef = useRef<number | null>(null)

  const [thread, setThread] = useState<Thread | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [issues, setIssues] = useState<Issue[]>([])
  const [issuesExpanded, setIssuesExpanded] = useState(false)
  const [issuesLoading, setIssuesLoading] = useState(false)
  const [issuesError, setIssuesError] = useState<string | null>(null)
  const [issuesLoaded, setIssuesLoaded] = useState(false)
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [issuesTotal, setIssuesTotal] = useState(0)

  useEffect(() => {
    const threadId = id ? Number(id) : null
    activeThreadIdRef.current = threadId
    setThread(null)
    setError(null)
    setIssues([])
    setIssuesExpanded(false)
    setIssuesLoading(false)
    setIssuesError(null)
    setIssuesLoaded(false)
    setNextPageToken(null)
    setIssuesTotal(0)

    async function fetchThread() {
      if (threadId === null) {
        setIsLoading(false)
        return
      }

      try {
        setIsLoading(true)
        const threadData = await threadsApi.get(threadId)
        if (activeThreadIdRef.current !== threadId) return
        setThread(threadData)
      } catch (err: unknown) {
        if (activeThreadIdRef.current !== threadId) return
        setError(getApiErrorDetail(err))
      } finally {
        if (activeThreadIdRef.current === threadId) {
          setIsLoading(false)
        }
      }
    }

    fetchThread()
  }, [id])

  async function loadIssuesPage(threadId: number, pageToken: string | null) {
    setIssuesLoading(true)
    setIssuesError(null)
    try {
      const data = await issuesApi.list(threadId, {
        page_size: 100,
        ...(pageToken ? { page_token: pageToken } : {}),
      })
      if (activeThreadIdRef.current !== threadId) return
      setIssues((prev) => (pageToken ? [...prev, ...data.issues] : data.issues))
      setNextPageToken(data.next_page_token)
      setIssuesTotal(data.total_count)
      setIssuesLoaded(true)
    } catch {
      if (activeThreadIdRef.current !== threadId) return
      setIssuesError('Failed to load issues')
    } finally {
      if (activeThreadIdRef.current === threadId) {
        setIssuesLoading(false)
      }
    }
  }

  function handleToggleIssues() {
    const next = !issuesExpanded
    setIssuesExpanded(next)
    if (next && thread && thread.total_issues !== null && !issuesLoaded) {
      void loadIssuesPage(thread.id, null)
    }
  }

  function handleLoadMore() {
    if (thread && thread.total_issues !== null && nextPageToken) {
      void loadIssuesPage(thread.id, nextPageToken)
    }
  }

  function handleIssueSnapshotChange(snapshot: IssueMutationSnapshot) {
    setIssues(snapshot.issues)
    setThread(snapshot.thread)
  }

  const handleEditSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const currentThread = thread!

    try {
      const updateData: {
        title: string
        format: string
        notes: string | null
        issues_remaining?: number
      } = {
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

      setThread(updatedThread)
      setIsEditOpen(false)

      if (updatedThread.total_issues !== null && issuesLoaded) {
        setIssues([])
        setNextPageToken(null)
        await loadIssuesPage(updatedThread.id, null)
      }
    } catch {
      console.error('Failed to update thread')
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
    })
    setIsEditOpen(true)
  }

  const getProgressPercentage = (): string | null => {
    if (!thread || thread.total_issues === null) return null

    const readCount = thread.total_issues - thread.issues_remaining
    const percentage = Math.round((readCount / thread.total_issues) * 100)

    return `${percentage}%`
  }

  const getIssuesReadCount = (): string | null => {
    if (!thread || thread.total_issues === null) return null

    const readCount = thread.total_issues - thread.issues_remaining
    return `${readCount} of ${thread.total_issues} issues read`
  }

  if (isLoading) {
    return <LoadingSpinner fullScreen />
  }

  if (error || !thread) {
    return (
      <div className="space-y-6 md:space-y-8 pb-20">
        <header className="px-2">
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase">
            Thread Details
          </h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            View thread information
          </p>
        </header>
        <div className="text-center text-stone-500">{error || 'Thread not found'}</div>
      </div>
    )
  }

  const isMigrated = thread.total_issues !== null
  const progressPercentage = getProgressPercentage()
  const issuesReadCount = getIssuesReadCount()

  return (
    <div className="space-y-6 md:space-y-8 pb-20">
      <header className="flex justify-between items-start px-2 gap-2 md:gap-4">
        <div className="flex-1 min-w-0">
          <button
            type="button"
            onClick={() => navigate('/queue')}
            className="text-xs font-black uppercase tracking-widest text-stone-500 hover:text-stone-300 mb-2"
          >
            ← Back to Queue
          </button>
          <h1 className="text-2xl md:text-4xl font-black tracking-tighter text-glow mb-1 uppercase truncate">
            {thread.title}
          </h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">
            {thread.format}
          </p>
        </div>
        <button
          type="button"
          onClick={openEditModal}
          className="h-9 md:h-12 px-4 md:px-5 glass-button text-[10px] md:text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl shrink-0"
        >
          Edit
        </button>
      </header>

      <div className="space-y-4 md:space-y-6">
        {progressPercentage && (
          <div className="glass-card p-3 md:p-4 space-y-3">
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
          <div className="glass-card p-3 md:p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">
              Notes
            </span>
            <p className="text-sm text-stone-300 whitespace-pre-wrap">{thread.notes}</p>
          </div>
        )}

        {isMigrated && (
          <div className="glass-card p-3 md:p-4 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">
                Issues ({issuesTotal > 0 ? issuesTotal : (thread.total_issues ?? issues.length)})
              </span>
              <button
                type="button"
                onClick={handleToggleIssues}
                className="text-xs font-black uppercase tracking-widest text-amber-400 hover:text-amber-300"
              >
                {issuesExpanded ? 'Collapse' : 'Expand'}
              </button>
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
                {issuesLoading && issues.length === 0 && (
                  <p className="text-xs text-stone-500">Loading issues...</p>
                )}

                {issuesError && !issuesLoading && (
                  <div className="space-y-2">
                    <p className="text-xs text-red-400">{issuesError}</p>
                    <button
                      type="button"
                      onClick={() => {
                        if (thread.total_issues !== null) {
                          setIssues([])
                          setNextPageToken(null)
                          void loadIssuesPage(thread.id, null)
                        }
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
                    {issues.map((issue) => (
                      <div
                        key={issue.id}
                        className={`flex items-center justify-between gap-3 p-2 rounded-lg border ${
                          issue.status === 'read'
                            ? 'bg-green-500/10 border-green-500/20'
                            : 'bg-white/5 border-white/10'
                        }`}
                      >
                        <span className="text-sm font-medium text-stone-300">
                          #{issue.issue_number}
                        </span>
                        <div className="flex items-center gap-3">
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
                    ))}
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
          <div className="glass-card p-3 md:p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">
              Issues Remaining
            </span>
            <p className="text-sm text-stone-300">{thread.issues_remaining} issues</p>
          </div>
        )}

        <div className="glass-card p-3 md:p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">
            Queue Position
          </span>
          <p className="text-sm text-stone-300">Position #{thread.queue_position}</p>
        </div>

        <div className="glass-card p-3 md:p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">
            Status
          </span>
          <p className="text-sm font-black uppercase">{thread.status}</p>
        </div>
      </div>

      <Modal
        isOpen={isEditOpen}
        title="Edit Thread"
        onClose={() => {
          setIsEditOpen(false)
        }}
        overlayClassName="edit-modal__overlay"
      >
        <div className="space-y-4">
          <form id="edit-thread-form" className="space-y-4" onSubmit={handleEditSubmit}>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                Title
              </label>
              <input
                value={editForm.title}
                onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
                required
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
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
                <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
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
                  className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                Notes
              </label>
              <textarea
                value={editForm.notes}
                onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
                className="w-full bg-white/5 border border-solid border-white/20 rounded-xl px-3 py-2 text-sm text-stone-300 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-400 transition-colors min-h-[80px]"
              />
            </div>
          </form>

          {thread.total_issues !== null && <IssueToggleList threadId={thread.id} />}

          <button
            type="submit"
            form="edit-thread-form"
            disabled={updateMutation.isPending}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
