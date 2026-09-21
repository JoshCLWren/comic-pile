import { useState } from 'react'
import type { Thread } from '../types'
import axios from 'axios'
import { migrationApi } from '../services/api'
import Modal from './Modal'

interface MigrationDialogProps {
  thread: Pick<Thread, 'id' | 'title'>
  onComplete: (thread: Thread) => void
  onSkip: () => void
  onClose: () => void
}

interface MigrationData {
  last_issue_read: number
  total_issues: number
}

export default function MigrationDialog({ thread, onComplete, onSkip, onClose }: MigrationDialogProps) {
  const [lastIssueRead, setLastIssueRead] = useState('')
  const [totalIssues, setTotalIssues] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showSkipConfirm, setShowSkipConfirm] = useState(false)

  const handleModalClose = () => {
    if (showSkipConfirm) {
      setShowSkipConfirm(false)
      return
    }
    onClose()
  }

  const lastRead = lastIssueRead === '' ? 0 : parseInt(lastIssueRead, 10)
  const total = totalIssues === '' ? 0 : parseInt(totalIssues, 10)

  const getWarningMessage = (): string | null => {
    if (lastIssueRead === '' || totalIssues === '' || isNaN(lastRead) || isNaN(total)) {
      return null
    }

    if (lastRead === 0) {
      return 'Starting fresh - all issues will be marked as unread.'
    }
    if (lastRead === total - 1 && total > 1) {
      return 'One issue away from completion!'
    }
    if (lastRead === total && total > 0) {
      return '🎉 Completing the series! This series will be marked as completed.'
    }
    return null
  }

  const warning = getWarningMessage()

  const getPreviewText = (): string | null => {
    if (lastIssueRead === '' || totalIssues === '' || isNaN(lastRead) || isNaN(total) || total === 0) {
      return null
    }

    if (lastRead === 0) {
      return `All ${total} issues will be marked as unread. 📌 Next time you'll start with #1`
    }

    if (lastRead >= total) {
      return `All ${total} issues will be marked as read. 🎉 Series will be completed!`
    }

    const unreadCount = total - lastRead
    return `We'll mark #1-#${lastRead} as read (✅) and track #${lastRead + 1}-#${total} as unread (${unreadCount} issues). 📌 Next time you'll read #${lastRead + 1}`
  }

  const previewText = getPreviewText()

  const validate = (): boolean => {
    setError(null)

    if (lastIssueRead === '' || totalIssues === '') {
      setError('Please fill in both fields')
      return false
    }

    if (isNaN(lastRead) || isNaN(total)) {
      setError('Please fill in both fields')
      return false
    }

    if (lastRead < 0 || total < 0) {
      setError('Values cannot be negative')
      return false
    }

    if (total === 0) {
      setError('Total issues must be greater than 0')
      return false
    }

    if (lastRead > total) {
      setError('Last issue read cannot exceed total issues')
      return false
    }

    return true
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!validate()) {
      return
    }

    setIsSubmitting(true)

    try {
      // SAFETY: lastRead and total are valid numbers after the numeric field validation above passes.
      const updatedThread: Thread = await migrationApi.migrateThread(thread.id, {
        last_issue_read: lastRead,
        total_issues: total,
      } as MigrationData)
      onComplete(updatedThread)
    } catch (err: unknown) {
      const errorMessage = axios.isAxiosError(err)
        ? err.response?.data?.detail || err.response?.data?.message || err.message
        : err instanceof Error ? err.message : 'An unexpected error occurred'
      setError(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSkipClick = () => {
    setShowSkipConfirm(true)
  }

  const handleSkipConfirm = () => {
    setShowSkipConfirm(false)
    onSkip()
  }

  return (
    <Modal
      isOpen
      title={`Track Issues for "${thread.title}"`}
      onClose={handleModalClose}
      data-testid="migration-dialog"
      autoFocus={true}
    >
      <form onSubmit={handleSubmit} className="space-y-4 md:space-y-6">
        <div className="space-y-1.5">
          <label htmlFor="last-issue-read" className="block text-sm font-semibold text-[var(--theme-text-primary)]">
            Last Issue Read <span className="text-[var(--theme-error)]" aria-hidden="true">*</span>
          </label>
          <input
            id="last-issue-read"
            type="number"
            min="0"
            value={lastIssueRead}
            onChange={(e) => setLastIssueRead(e.target.value)}
            placeholder="0"
            className="form-control w-full"
            autoFocus
            disabled={isSubmitting}
          />
          <span className="text-xs text-[var(--theme-text-muted)]">
            The highest issue number you've finished reading (0 if starting fresh)
          </span>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="total-issues" className="block text-sm font-semibold text-[var(--theme-text-primary)]">
            Total Issues <span className="text-[var(--theme-error)]" aria-hidden="true">*</span>
          </label>
          <input
            id="total-issues"
            type="number"
            min="1"
            value={totalIssues}
            onChange={(e) => setTotalIssues(e.target.value)}
            placeholder="e.g., 50"
            className="form-control w-full"
            disabled={isSubmitting}
          />
          <span className="text-xs text-[var(--theme-text-muted)]">
            The total number of issues in this series
          </span>
        </div>

        {previewText && (
          <div className="rounded-lg border border-[color-mix(in_srgb,_var(--theme-comic-accent)_20%,_transparent)] bg-[color-mix(in_srgb,_var(--theme-comic-accent)_10%,_transparent)] p-3.5">
            <p className="text-sm leading-relaxed text-[var(--theme-comic-accent)]">{previewText}</p>
          </div>
        )}

        {warning && (
          <div className="rounded-lg border border-[color-mix(in_srgb,_var(--theme-warning)_30%,_transparent)] bg-[color-mix(in_srgb,_var(--theme-warning)_10%,_transparent)] p-3" role="status">
            <p className="text-sm leading-relaxed text-[var(--theme-warning)]">{warning}</p>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-[color-mix(in_srgb,_var(--theme-error)_30%,_transparent)] bg-[color-mix(in_srgb,_var(--theme-error)_20%,_transparent)] p-3" role="alert">
            <p className="text-sm text-[var(--theme-error)]">{error}</p>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={handleSkipClick}
            className="px-5 py-2.5 text-sm font-semibold rounded-lg transition-colors text-[var(--theme-text-primary)] bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] hover:bg-[color-mix(in_srgb,_white_20%,_transparent)] disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isSubmitting}
          >
            Skip
          </button>
          <button
            type="submit"
            className="px-5 py-2.5 text-sm font-semibold rounded-lg transition-colors text-white bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Migrating...' : 'Start Tracking'}
          </button>
        </div>
      </form>

      {showSkipConfirm && (
        <div className="absolute inset-0 z-10 flex items-center justify-center p-4 bg-[color-mix(in_srgb,_var(--theme-bg-page)_90%,_transparent)] rounded-lg">
          <div className="w-full max-w-xs rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-page)] p-6 shadow-[0_20px_25px_-5px_rgba(0,0,0,0.3)]">
            <h3 className="mb-2 text-base font-bold text-[var(--theme-text-primary)]">
              Skip migration?
            </h3>
            <p className="mb-5 text-sm leading-relaxed text-[var(--theme-text-primary)]">
              You can migrate this thread later from the queue page.
            </p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowSkipConfirm(false)}
                className="px-5 py-2.5 text-sm font-semibold rounded-lg transition-colors text-[var(--theme-text-primary)] bg-[var(--theme-bg-panel)] border border-[var(--theme-border)] hover:bg-[color-mix(in_srgb,_white_20%,_transparent)] disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={isSubmitting}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSkipConfirm}
                className="px-5 py-2.5 text-sm font-semibold rounded-lg transition-colors text-white bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={isSubmitting}
              >
                Yes, Skip
              </button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}