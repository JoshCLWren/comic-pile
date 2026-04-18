import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import Modal from '../components/Modal'
import LoadingSpinner from '../components/LoadingSpinner'
import { threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import type { Thread, Issue } from '../types'
import { CollectionBadge } from '../pages/QueuePage/CollectionBadge'
import { FormatSelect } from '../pages/QueuePage/FormatSelect'
import { useUpdateThread } from '../hooks/useThread'
import { useThreadReviews } from '../hooks/useReview'
import { isReviewsFeatureEnabled } from '../config/featureFlags'
import { getApiErrorDetail } from '../utils/apiError'
import type { ChangeEvent, FormEvent } from 'react'
import { DEFAULT_CREATE_STATE, type QueueFormState } from '../pages/QueuePage/types'
import { IssueToggleList } from '../pages/QueuePage/IssueToggleList'

export default function ThreadDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const updateMutation = useUpdateThread()
  const { reviews, getThreadReviews, isPending: reviewsLoading } = useThreadReviews()
  const reviewsEnabled = isReviewsFeatureEnabled()

  const [thread, setThread] = useState<Thread | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isEditOpen, setIsEditOpen] = useState(false)
  const [editForm, setEditForm] = useState<QueueFormState>(DEFAULT_CREATE_STATE)
  const [issues, setIssues] = useState<Issue[]>([])
  const [issuesExpanded, setIssuesExpanded] = useState(false)

  useEffect(() => {
    async function fetchThread() {
      if (!id) return

      try {
        setIsLoading(true)
        const threadData = await threadsApi.get(Number(id))
        setThread(threadData)

        if (threadData.total_issues !== null) {
          await fetchIssues(Number(id))
        }

        if (reviewsEnabled) {
          // Fetch reviews for this thread
          try {
            await getThreadReviews(Number(id))
          } catch (reviewError: unknown) {
            console.error('Failed to fetch reviews:', getApiErrorDetail(reviewError))
            // Don't let review failures break the entire page
          }
        }
      } catch (err: unknown) {
        setError(getApiErrorDetail(err))
      } finally {
        setIsLoading(false)
      }
    }

    fetchThread()
  }, [id, getThreadReviews, reviewsEnabled])

  async function fetchIssues(threadId: number) {
    try {
      const allIssues: Issue[] = []
      let nextPageToken: string | null = null

      do {
        const data = await issuesApi.list(threadId, {
          page_size: 100,
          ...(nextPageToken ? { page_token: nextPageToken } : {}),
        })
        allIssues.push(...data.issues)
        nextPageToken = data.next_page_token
      } while (nextPageToken)

      setIssues(allIssues)
    } catch (err: unknown) {
      console.error('Failed to fetch issues:', err)
    }
  }

  const handleEditSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!thread) return

    try {
      const updateData: { title: string; format: string; notes: string | null; issues_remaining?: number } = {
        title: editForm.title,
        format: editForm.format,
        notes: editForm.notes || null,
      }

      if (thread.total_issues === null) {
        updateData.issues_remaining = Number(editForm.issuesRemaining)
      }

      const updatedThread = await updateMutation.mutate({
        id: thread.id,
        data: updateData,
      })

      setThread(updatedThread)
      setIsEditOpen(false)

      if (updatedThread.total_issues !== null) {
        await fetchIssues(updatedThread.id)
      }
    } catch {
      console.error('Failed to update thread')
    }
  }

  const openEditModal = () => {
    if (!thread) return

    setEditForm({
      title: thread.title,
      format: thread.format,
      issuesRemaining: thread.issues_remaining,
      notes: thread.notes || '',
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
      <div className="space-y-8 pb-20">
        <header className="px-2">
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">Thread Details</h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">View thread information</p>
        </header>
        <div className="text-center text-stone-500">
          {error || 'Thread not found'}
        </div>
      </div>
    )
  }

  const isMigrated = thread.total_issues !== null
  const progressPercentage = getProgressPercentage()
  const issuesReadCount = getIssuesReadCount()

  return (
    <div className="space-y-8 pb-20">
      <header className="flex justify-between items-start px-2 gap-4">
        <div className="flex-1">
          <button
            type="button"
            onClick={() => navigate('/queue')}
            className="text-xs font-black uppercase tracking-widest text-stone-500 hover:text-stone-300 mb-2"
          >
            ← Back to Queue
          </button>
          <h1 className="text-4xl font-black tracking-tighter text-glow mb-1 uppercase">{thread.title}</h1>
          <p className="text-[10px] font-bold text-stone-500 uppercase tracking-widest">{thread.format}</p>
        </div>
        <button
          type="button"
          onClick={openEditModal}
          className="h-12 px-5 glass-button text-xs font-black uppercase tracking-widest whitespace-nowrap shadow-xl"
        >
          Edit
        </button>
      </header>

      <div className="space-y-6">
        {thread.collection_id && (
          <div className="flex">
            <CollectionBadge collectionId={thread.collection_id} />
          </div>
        )}

        {progressPercentage && (
          <div className="glass-card p-4 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">Reading Progress</span>
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
          <div className="glass-card p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">Notes</span>
            <p className="text-sm text-stone-300 whitespace-pre-wrap">{thread.notes}</p>
          </div>
        )}

        {isMigrated && issues.length > 0 && (
          <div className="glass-card p-4 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">
                Issues ({issues.length})
              </span>
              <button
                type="button"
                onClick={() => setIssuesExpanded(!issuesExpanded)}
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
                {issues.map((issue) => (
                  <div
                    key={issue.id}
                    className={`flex items-center justify-between p-2 rounded-lg border ${
                      issue.status === 'read'
                        ? 'bg-green-500/10 border-green-500/20'
                        : 'bg-white/5 border-white/10'
                    }`}
                  >
                    <span className="text-sm font-medium text-stone-300">
                      #{issue.issue_number}
                    </span>
                    <span className="text-xs font-black uppercase tracking-widest">
                      {issue.status === 'read' ? (
                        <span className="text-green-400">Read</span>
                      ) : (
                        <span className="text-stone-500">Unread</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isMigrated && (
          <div className="glass-card p-4 space-y-2">
            <span className="text-xs font-black uppercase tracking-widest text-stone-500">Issues Remaining</span>
            <p className="text-sm text-stone-300">{thread.issues_remaining} issues</p>
          </div>
        )}

        {reviewsEnabled && (
          <div className="glass-card p-4 space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-xs font-black uppercase tracking-widest text-stone-500">
                Reviews {reviews.length > 0 && `(${reviews.length})`}
              </span>
            </div>

            {reviewsLoading && (
              <p className="text-xs text-stone-500">Loading reviews...</p>
            )}

            {!reviewsLoading && reviews.length === 0 && (
              <p className="text-xs text-stone-500">No reviews yet.</p>
            )}

            {!reviewsLoading && reviews.length > 0 && (
              <div className="space-y-3">
                {reviews.map((review) => (
                  <div key={review.id} className="p-3 bg-white/5 rounded-lg border border-white/10 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-lg font-black text-amber-400">
                          {review.rating.toFixed(1)}
                        </span>
                        {review.issue_number && (
                          <span className="text-xs text-stone-400">
                            #{review.issue_number}
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-stone-500">
                        {new Date(review.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    {review.review_text && (
                      <p className="text-sm text-stone-300 leading-relaxed">
                        {review.review_text}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="glass-card p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">Queue Position</span>
          <p className="text-sm text-stone-300">Position #{thread.queue_position}</p>
        </div>

        <div className="glass-card p-4 space-y-2">
          <span className="text-xs font-black uppercase tracking-widest text-stone-500">Status</span>
          <p className="text-sm font-black uppercase">{thread.status}</p>
        </div>
      </div>

      <Modal isOpen={isEditOpen} title="Edit Thread" onClose={() => { setIsEditOpen(false) }} overlayClassName="edit-modal__overlay">
        <div className="space-y-4">
          <form id="edit-thread-form" className="space-y-4" onSubmit={handleEditSubmit}>
            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Title</label>
              <input
                value={editForm.title}
                onChange={(event) => setEditForm({ ...editForm, title: event.target.value })}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                required
              />
            </div>

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Format</label>
              <FormatSelect
                value={editForm.format}
                onChange={(value) => setEditForm({ ...editForm, format: value })}
                required
              />
            </div>

            {thread.total_issues === null && (
              <div className="space-y-2">
                <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Issues Remaining</label>
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
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                />
              </div>
            )}

            <div className="space-y-2">
              <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Notes</label>
              <textarea
                value={editForm.notes}
                onChange={(event) => setEditForm({ ...editForm, notes: event.target.value })}
                className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300 min-h-[80px]"
              />
            </div>
          </form>

          {thread.total_issues !== null && (
            <IssueToggleList threadId={thread.id} />
          )}

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
