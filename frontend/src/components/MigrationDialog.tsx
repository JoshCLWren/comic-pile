import { useState, useEffect } from 'react'
import type { Thread } from '../types'
import { migrationApi } from '../services/api'
import './MigrationDialog.css'

interface MigrationDialogProps {
  thread: Thread
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (showSkipConfirm) {
          setShowSkipConfirm(false)
        } else {
          onClose()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose, showSkipConfirm])

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
      return '🎉 Completing the series! Thread will be marked as completed.'
    }
    if (total > 0 && lastRead > total * 0.9 && lastRead < total) {
      return 'Almost done! Just a few issues left.'
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
      return `All ${total} issues will be marked as read. 🎉 Thread will be completed!`
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
      setError('Please enter valid numbers')
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
      const updatedThread: Thread = await migrationApi.migrateThread(thread.id, {
        last_issue_read: lastRead,
        total_issues: total,
      } as MigrationData)
      onComplete(updatedThread)
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'An unexpected error occurred'
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

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !showSkipConfirm) {
      onClose()
    }
  }

  return (
    <div
      className="migration-dialog__overlay"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="migration-dialog-title"
    >
      <div className="migration-dialog">
        <div className="migration-dialog__header">
          <h2 id="migration-dialog-title" className="migration-dialog__title">
            Track Issues for "{thread.title}"
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="migration-dialog__close-btn"
            aria-label="Close dialog"
            disabled={isSubmitting}
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} className="migration-dialog__form">
          <div className="migration-dialog__field">
            <label htmlFor="last-issue-read" className="migration-dialog__label">
              Last Issue Read <span className="migration-dialog__required">*</span>
            </label>
            <input
              id="last-issue-read"
              type="number"
              min="0"
              value={lastIssueRead}
              onChange={(e) => setLastIssueRead(e.target.value)}
              placeholder="0"
              className="migration-dialog__input"
              autoFocus
              disabled={isSubmitting}
            />
            <span className="migration-dialog__hint">
              The highest issue number you've finished reading (0 if starting fresh)
            </span>
          </div>

          <div className="migration-dialog__field">
            <label htmlFor="total-issues" className="migration-dialog__label">
              Total Issues <span className="migration-dialog__required">*</span>
            </label>
            <input
              id="total-issues"
              type="number"
              min="1"
              value={totalIssues}
              onChange={(e) => setTotalIssues(e.target.value)}
              placeholder="e.g., 50"
              className="migration-dialog__input"
              disabled={isSubmitting}
            />
            <span className="migration-dialog__hint">
              The total number of issues in this series
            </span>
          </div>

          {previewText && (
            <div className="migration-preview">
              <div className="migration-preview__content">
                {previewText}
              </div>
            </div>
          )}

          {warning && (
            <div className="migration-warning" role="status">
              {warning}
            </div>
          )}

          {error && (
            <div className="migration-dialog__error" role="alert">
              {error}
            </div>
          )}

          <div className="migration-dialog__actions">
            <button
              type="button"
              onClick={handleSkipClick}
              className="migration-dialog__btn migration-dialog__btn--secondary"
              disabled={isSubmitting}
            >
              Skip
            </button>
            <button
              type="submit"
              className="migration-dialog__btn migration-dialog__btn--primary"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Migrating...' : 'Start Tracking'}
            </button>
          </div>
        </form>

        {showSkipConfirm && (
          <div className="migration-dialog__confirm-overlay">
            <div className="migration-dialog__confirm-dialog">
              <p className="migration-dialog__confirm-title">Skip migration?</p>
              <p className="migration-dialog__confirm-message">
                You can migrate this thread later from the queue page.
              </p>
              <div className="migration-dialog__confirm-actions">
                <button
                  type="button"
                  onClick={() => setShowSkipConfirm(false)}
                  className="migration-dialog__btn migration-dialog__btn--secondary"
                  disabled={isSubmitting}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSkipConfirm}
                  className="migration-dialog__btn migration-dialog__btn--primary"
                  disabled={isSubmitting}
                >
                  Yes, Skip
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
