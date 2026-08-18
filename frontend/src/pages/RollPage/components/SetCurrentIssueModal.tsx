import { useEffect, useState, useCallback } from 'react'
import type { FormEvent, ChangeEvent } from 'react'
import Modal from '../../../components/Modal'
import { issuesApi } from '../../../services/api-issues'
import { getApiErrorDetail } from '../../../utils/apiError'
import type { Issue } from '../../../types'

interface SetCurrentIssueModalProps {
  threadId: number
  currentIssueNumber: string | null
  onClose: () => void
  onSuccess: (response: {
    thread_id: number
    title: string
    format: string
    issues_remaining: number
    queue_position: number
    issue_id: number | null
    issue_number: string | null
    next_issue_id: number | null
    next_issue_number: string | null
    total_issues: number | null
    reading_progress: string | null
  }) => void
}

export function SetCurrentIssueModal({
  threadId,
  currentIssueNumber,
  onClose,
  onSuccess,
}: SetCurrentIssueModalProps) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [selectedIssueNumber, setSelectedIssueNumber] = useState<string>('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadIssues = useCallback(async () => {
    try {
      setIsLoading(true)
      const allIssues: Issue[] = []
      let nextPageToken: string | null = null

      while (true) {
        const data = await issuesApi.list(threadId, {
          page_size: 100,
          ...(nextPageToken ? { page_token: nextPageToken } : {}),
        })
        allIssues.push(...data.issues)

        if (!data.next_page_token) {
          break
        }
        nextPageToken = data.next_page_token
      }

      allIssues.sort((a, b) => {
        const posA = a.position ?? 0
        const posB = b.position ?? 0
        if (posA !== posB) return posA - posB
        return a.issue_number.localeCompare(b.issue_number, undefined, { numeric: true })
      })

      setIssues(allIssues)

      if (currentIssueNumber && !selectedIssueNumber) {
        const currentIssue = allIssues.find((i) => i.issue_number === currentIssueNumber)
        if (currentIssue) {
          const currentIndex = allIssues.indexOf(currentIssue)
          if (currentIndex < allIssues.length - 1) {
            setSelectedIssueNumber(allIssues[currentIndex + 1].issue_number)
          } else {
            setSelectedIssueNumber(currentIssueNumber)
          }
        }
      } else if (allIssues.length > 0) {
        const firstUnread = allIssues.find((i) => i.status === 'unread')
        setSelectedIssueNumber(firstUnread?.issue_number ?? allIssues[0].issue_number)
      }
    } catch (err) {
      console.error('Failed to load issues:', err)
      setError(getApiErrorDetail(err))
    } finally {
      setIsLoading(false)
    }
  }, [threadId, currentIssueNumber, selectedIssueNumber])

  useEffect(() => {
    loadIssues()
  }, [loadIssues])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!selectedIssueNumber.trim() || isSubmitting) return

    setIsSubmitting(true)
    setError(null)

    try {
      const response = await issuesApi.setCurrentIssue(threadId, selectedIssueNumber.trim())
      onSuccess(response)
    } catch (err) {
      console.error('Failed to set current issue:', err)
      setError(getApiErrorDetail(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  function handleIssueSelect(issueNumber: string) {
    setSelectedIssueNumber(issueNumber)
  }

  if (isLoading) {
    return (
      <Modal isOpen={true} title="Set Current Issue" onClose={onClose}>
        <div className="text-center py-8 text-stone-400">Loading issues…</div>
      </Modal>
    )
  }

  const unreadIssues = issues.filter((i) => i.status === 'unread')
  const readIssues = issues.filter((i) => i.status === 'read')

  return (
    <Modal isOpen={true} title="Set Current Issue" onClose={onClose}>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <p className="text-xs text-stone-400">
          Choose the issue that should be the current/next issue to read. All earlier issues
          will be marked read, and the selected issue will be set as unread/current.
        </p>

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="space-y-2 max-h-60 overflow-auto">
          {unreadIssues.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-bold uppercase tracking-widest text-amber-400">Unread</p>
              {unreadIssues.map((issue) => (
                <button
                  key={issue.id}
                  type="button"
                  onClick={() => handleIssueSelect(issue.issue_number)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    selectedIssueNumber === issue.issue_number
                      ? 'bg-amber-600/30 border border-amber-500 text-amber-300'
                      : 'bg-white/5 border border-white/10 text-stone-300 hover:bg-white/10'
                  }`}
                >
                  #{issue.issue_number} {issue.status === 'read' ? '✅' : '🟢'}
                </button>
              ))}
            </div>
          )}

          {readIssues.length > 0 && (
            <div className="space-y-1">
              <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Already Read</p>
              {readIssues.map((issue) => (
                <button
                  key={issue.id}
                  type="button"
                  onClick={() => handleIssueSelect(issue.issue_number)}
                  className={`w-full text-left px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                    selectedIssueNumber === issue.issue_number
                      ? 'bg-amber-600/30 border border-amber-500 text-amber-300'
                      : 'bg-white/5 border border-white/10 text-stone-500 hover:bg-white/10'
                  }`}
                >
                  #{issue.issue_number} ✅
                </button>
              ))}
            </div>
          )}

          {issues.length === 0 && (
            <p className="text-center text-stone-500 py-4">No issues found for this thread.</p>
          )}
        </div>

        <div className="flex gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="flex-1 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60 border border-white/20 bg-white/5 hover:bg-white/10"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting || !selectedIssueNumber.trim()}
            className="flex-1 py-3 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-60"
          >
            {isSubmitting ? 'Setting...' : 'Set Current Issue'}
          </button>
        </div>
      </form>
    </Modal>
  )
}