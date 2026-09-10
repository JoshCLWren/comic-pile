import { useState, useEffect, useCallback } from 'react'
import type { KeyboardEvent } from 'react'
import Modal from './Modal'
import { issuesApi } from '../services/api-issues'
import type { Issue } from '../types'

interface IssueCorrectionDialogProps {
  isOpen: boolean
  threadId: number
  currentIssueNumber: string | null | undefined
  totalIssues: number | null | undefined
  threadTitle: string
  onClose: () => void
  onSuccess: () => void
}

export default function IssueCorrectionDialog({
  isOpen,
  threadId,
  currentIssueNumber,
  totalIssues,
  threadTitle,
  onClose,
  onSuccess,
}: IssueCorrectionDialogProps) {
  const [selectedIssueNumber, setSelectedIssueNumber] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingIssues, setIsLoadingIssues] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [allIssues, setAllIssues] = useState<Issue[]>([])
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false)
  const [insertPosition, setInsertPosition] = useState<string>('end')

  const hasNumericSelection = /^\d+$/.test(selectedIssueNumber.trim())

  const loadAllIssues = useCallback(async () => {
    const loadedIssues: Issue[] = []
    const seenPageTokens = new Set<string>()
    let nextPageToken: string | null = null

    while (true) {
      const params = { page_size: 100 } satisfies { page_size: number; page_token?: string }
      if (nextPageToken) {
        params.page_token = nextPageToken
      }
      const data = await issuesApi.list(threadId, params)

      if (!data.issues || data.issues.length === 0) {
        break
      }

      loadedIssues.push(...(data.issues || []))

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        break
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }

    return loadedIssues
  }, [threadId])

  const fetchIssues = useCallback(async (retryAttempt = 0) => {
    setIsLoadingIssues(true)
    setError(null)
    try {
      const loadedIssues = await loadAllIssues()

      setAllIssues(loadedIssues)
      if (!currentIssueNumber) {
        const firstUnreadIssue = loadedIssues.find((issue) => issue.status !== 'read')
        setSelectedIssueNumber(firstUnreadIssue?.issue_number ?? loadedIssues[0]?.issue_number ?? '')
      }
      setHasLoadedOnce(true)
    } catch (err) {
      console.error('Failed to load issues:', err)
      if (retryAttempt < 2) {
        await fetchIssues(retryAttempt + 1)
      } else {
        setError('Failed to load issues after multiple attempts. Please try again.')
      }
    } finally {
      setIsLoadingIssues(false)
    }
  }, [currentIssueNumber, loadAllIssues])

  useEffect(() => {
    if (isOpen) {
      setSelectedIssueNumber(currentIssueNumber ?? '')
      setInsertPosition('end')
      fetchIssues()
    }
  }, [isOpen, currentIssueNumber, fetchIssues])

  const handleSubmit = useCallback(async () => {
    const targetNumber = selectedIssueNumber.trim()
    if (!targetNumber) {
      setError('Please enter an issue identifier')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      let targetIssue = allIssues.find((issue) => issue.issue_number === targetNumber)
      if (!targetIssue) {
        const insertAfterIssueId =
          insertPosition !== 'start' && insertPosition !== 'end' ? Number(insertPosition) : null
        const createdIssues = await issuesApi.create(threadId, targetNumber, {
          insert_after_issue_id: insertAfterIssueId,
        })
        targetIssue = createdIssues.issues.find((issue) => issue.issue_number === targetNumber)

        if (!targetIssue) {
          throw new Error('Created issue was not returned by the API')
        }

        if (insertPosition === 'start') {
          await issuesApi.move(targetIssue.id, null)
        }
      }

      const orderedIssues = await loadAllIssues()
      const targetIndex = orderedIssues.findIndex((issue) => issue.issue_number === targetNumber)

      if (targetIndex === -1) {
        throw new Error('Issue not found after update')
      }

      const issuesBeforeTarget = orderedIssues.slice(0, targetIndex)
      const unreadBeforeTarget = issuesBeforeTarget.filter((issue) => issue.status !== 'read')
      await Promise.all(unreadBeforeTarget.map((issue) => issuesApi.markRead(issue.id)))

      if (targetIssue.status === 'read') {
        await issuesApi.markUnread(targetIssue.id)
      }

      onSuccess()
      onClose()
    } catch (err) {
      console.error('Failed to update issue:', err)
      setError('Failed to update issue. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [selectedIssueNumber, allIssues, insertPosition, threadId, loadAllIssues, onSuccess, onClose])

  const adjustIssue = useCallback((delta: number) => {
    const currentValue = selectedIssueNumber

    if (!currentValue || !/^\d+$/.test(currentValue)) {
      setError('Use the text field for annuals or specials')
      return
    }

    const current = parseInt(currentValue, 10)

    if (isNaN(current)) {
      setError('Invalid issue number')
      return
    }

    const newNum = current + delta
    const min = 1
    const max = totalIssues !== null && totalIssues !== undefined ? totalIssues : 999

    if (newNum >= min && newNum <= max) {
      setSelectedIssueNumber(newNum.toString())
      setError(null)
    }
  }, [selectedIssueNumber, totalIssues])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  if (!isOpen) return null

  return (
    <Modal
      isOpen={isOpen}
      title="Fix Issue Number"
      onClose={onClose}
      data-testid="issue-correction-dialog"
    >
      <div className="space-y-4">
        <p className="text-sm text-stone-400">
          Reading: <span className="text-stone-200 font-bold">{threadTitle}</span>
        </p>

        {isLoadingIssues ? (
          <div className="bg-amber-600/10 border border-amber-600/20 rounded-lg p-6 text-center">
            <p className="text-sm text-stone-400">Loading issues...</p>
          </div>
        ) : (
          <div className="bg-amber-600/10 border border-amber-600/20 rounded-lg p-4">
            <label htmlFor="issue-number" className="block text-sm font-bold text-stone-300 mb-2">
              What issue are you currently on?
            </label>

            <div className="flex items-center justify-center gap-4">
              <button
                type="button"
                onClick={() => adjustIssue(-1)}
                disabled={isLoading || !hasNumericSelection}
                className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
                aria-label="Decrease issue number"
              >
                −
              </button>

              <div className="flex-1 text-center">
                <input
                  id="issue-number"
                  type="text"
                  inputMode="text"
                  maxLength={50}
                  value={selectedIssueNumber}
                  onChange={(e) => {
                    setSelectedIssueNumber(e.target.value)
                    setError(null)
                  }}
                  onKeyDown={handleKeyDown}
                  disabled={isLoading}
                  className="w-full text-center text-3xl font-black rounded-lg py-3 px-4 form-control"
                  aria-describedby="issue-range"
                />
                {totalIssues && (
                  <p id="issue-range" className="text-xs text-stone-500 mt-1">
                    of {totalIssues}
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={() => adjustIssue(1)}
                disabled={isLoading || !hasNumericSelection}
                className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
                aria-label="Increase issue number"
              >
                +
              </button>
            </div>
            {!allIssues.some((issue) => issue.issue_number === selectedIssueNumber.trim()) && (
              <div className="mt-4">
                <label htmlFor="issue-position" className="block text-xs font-bold text-stone-400 mb-2">
                  Place new issue
                </label>
                <select
                  id="issue-position"
                  value={insertPosition}
                  onChange={(event) => setInsertPosition(event.target.value)}
                  disabled={isLoading}
                  className="w-full rounded-lg py-2 px-3 text-sm form-control"
                >
                  <option value="end">At the end</option>
                  <option value="start">At the beginning</option>
                  {allIssues.map((issue) => (
                    <option key={issue.id} value={issue.id}>
                      After {issue.issue_number}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-800/20 border border-red-800/50 rounded-lg">
            <p className="text-sm text-red-400 text-center mb-2">{error}</p>
            {!isLoadingIssues && !hasLoadedOnce && (
              <button
                type="button"
                onClick={() => fetchIssues()}
                className="w-full py-2 bg-red-800/40 hover:bg-red-800/60 border border-red-800/60 rounded text-xs font-bold uppercase tracking-wider transition-all"
              >
                Retry
              </button>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="flex-1 py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-sm font-black uppercase tracking-wider transition-all disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isLoading}
            className="flex-1 py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-sm font-black uppercase tracking-wider transition-all disabled:opacity-50"
          >
            {isLoading ? 'Updating...' : 'Update'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
