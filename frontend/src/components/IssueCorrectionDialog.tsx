import { useState, useEffect, useCallback, useRef } from 'react'
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
  const keyHoldTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const keyHoldDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchIssues = useCallback(async (retryAttempt = 0) => {
    setIsLoadingIssues(true)
    setError(null)
    try {
      const allIssues: Issue[] = []
      const seenPageTokens = new Set<string>()
      let nextPageToken: string | null = null

while (true) {
      const data = await issuesApi.list(threadId, {
        page_size: 100,
        ...(nextPageToken ? { page_token: nextPageToken } : {}),
      })

      if (!data.issues || data.issues.length === 0) {
        break
      }

      allIssues.push(...(data.issues || []))

      if (!data.next_page_token || seenPageTokens.has(data.next_page_token)) {
        break
      }

      seenPageTokens.add(data.next_page_token)
      nextPageToken = data.next_page_token
    }

    setAllIssues(allIssues)
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
  }, [threadId])

  useEffect(() => {
    if (isOpen && currentIssueNumber) {
      setSelectedIssueNumber(currentIssueNumber)
      fetchIssues()
    }
  }, [isOpen, currentIssueNumber, fetchIssues])

  const handleEscape = useCallback((e: globalThis.KeyboardEvent) => {
    if (e.key === 'Escape' && isOpen) {
      onClose()
    }
  }, [isOpen, onClose])

  useEffect(() => {
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [handleEscape])

  const handleSubmit = useCallback(async () => {
    const targetNumber = selectedIssueNumber.trim()
    if (!targetNumber) {
      setError('Please enter an issue number')
      return
    }

    const targetNum = parseInt(targetNumber, 10)
    if (isNaN(targetNum)) {
      setError('Please enter a valid number')
      return
    }

    const currentNum = currentIssueNumber !== null && currentIssueNumber !== undefined
      ? parseInt(currentIssueNumber, 10)
      : 0

    if (targetNum < 1) {
      setError('Issue number must be at least 1')
      return
    }

    if (totalIssues && targetNum > totalIssues) {
      setError(`Issue number cannot exceed total issues (${totalIssues})`)
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const targetIssue = allIssues.find((issue) => issue.issue_number === targetNumber)
      if (!targetIssue) {
        const availableIssueNumbers = allIssues.map(i => i.issue_number).sort((a, b) => parseInt(a, 10) - parseInt(b, 10))
        setError(`Issue #${targetNumber} not found. Available issues: ${availableIssueNumbers.slice(0, 5).join(', ')}${availableIssueNumbers.length > 5 ? '...' : ''}`)
        setIsLoading(false)
        return
      }

      if (targetNum > currentNum) {
        const issuesToMarkRead = allIssues.filter(
          (issue) => {
            const issueNum = parseInt(issue.issue_number, 10)
            return issueNum >= currentNum && issueNum < targetNum && issue.status !== 'read'
          }
        )

        await Promise.all(issuesToMarkRead.map(issue => issuesApi.markRead(issue.id)))

        if (targetIssue.status === 'read') {
          await issuesApi.markUnread(targetIssue.id)
        }
      } else if (targetNum < currentNum) {
        if (targetIssue.status === 'read') {
          await issuesApi.markUnread(targetIssue.id)
        }
      }

      onSuccess()
      onClose()
    } catch (err) {
      console.error('Failed to update issue:', err)
      setError('Failed to update issue. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }, [selectedIssueNumber, currentIssueNumber, totalIssues, allIssues, onSuccess, onClose])

const adjustIssue = useCallback((delta: number) => {
    const currentValue = selectedIssueNumber

    if (!currentValue || !/^\d+$/.test(currentValue)) {
      setError('Please enter a valid number first')
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

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  const handleKeyHold = useCallback((delta: number, isStart: boolean) => {
    if (isStart) {
      adjustIssue(delta)
      keyHoldDelayRef.current = setTimeout(() => {
        keyHoldTimerRef.current = setInterval(() => {
          adjustIssue(delta)
        }, 50)
      }, 300)
    } else {
      if (keyHoldTimerRef.current) {
        clearInterval(keyHoldTimerRef.current)
        keyHoldTimerRef.current = null
      }
      if (keyHoldDelayRef.current) {
        clearTimeout(keyHoldDelayRef.current)
        keyHoldDelayRef.current = null
      }
    }
  }, [adjustIssue])

  const handleButtonKeyDown = useCallback((e: React.KeyboardEvent, delta: number) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleKeyHold(delta, true)
    }
  }, [handleKeyHold])

  const handleButtonKeyUp = useCallback((e: React.KeyboardEvent, delta: number) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleKeyHold(delta, false)
    }
  }, [handleKeyHold])

  useEffect(() => {
    return () => {
      if (keyHoldTimerRef.current) {
        clearInterval(keyHoldTimerRef.current)
      }
      if (keyHoldDelayRef.current) {
        clearTimeout(keyHoldDelayRef.current)
      }
    }
  }, [])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="issue-correction-title"
    >
      <div
        className="relative w-full max-w-md glass-card p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 pb-4">
          <h2 id="issue-correction-title" className="text-xl font-black tracking-tight text-stone-200 uppercase">
            Correct Issue Number
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-stone-500 hover:text-stone-300 transition-colors text-2xl leading-none"
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

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
          onMouseDown={() => handleKeyHold(-1, true)}
          onMouseUp={() => handleKeyHold(-1, false)}
          onMouseLeave={() => handleKeyHold(-1, false)}
          onTouchStart={() => handleKeyHold(-1, true)}
          onTouchEnd={() => handleKeyHold(-1, false)}
          onKeyDown={(e) => handleButtonKeyDown(e, -1)}
          onKeyUp={(e) => handleButtonKeyUp(e, -1)}
          disabled={isLoading}
          className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
          aria-label="Decrease issue number"
        >
          −
        </button>

              <div className="flex-1 text-center">
<input
              id="issue-number"
              type="number"
              min="1"
              max={totalIssues || undefined}
              value={selectedIssueNumber}
              onChange={(e) => setSelectedIssueNumber(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              className="w-full text-center text-3xl font-black bg-white/5 border border-white/10 rounded-lg py-3 px-4 text-stone-200 focus:outline-none focus:ring-2 focus:ring-amber-500"
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
            onMouseDown={() => handleKeyHold(1, true)}
            onMouseUp={() => handleKeyHold(1, false)}
            onMouseLeave={() => handleKeyHold(1, false)}
            onTouchStart={() => handleKeyHold(1, true)}
            onTouchEnd={() => handleKeyHold(1, false)}
            onKeyDown={(e) => handleButtonKeyDown(e, 1)}
            onKeyUp={(e) => handleButtonKeyUp(e, 1)}
            disabled={isLoading}
            className="w-14 h-14 flex items-center justify-center bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-2xl font-bold text-stone-200 transition-all disabled:opacity-50 active:scale-95 focus:ring-2 focus:ring-amber-500"
            aria-label="Increase issue number"
          >
            +
          </button>
            </div>
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
      </div>
    </div>
  )
}
