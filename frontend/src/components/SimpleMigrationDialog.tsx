import { useState, useEffect, useRef } from 'react'
import './MigrationDialog.css'

interface SimpleMigrationDialogProps {
  threadTitle: string
  onComplete: (issueNumber: string) => void
  onClose: () => void
}

export default function SimpleMigrationDialog({
  threadTitle,
  onComplete,
  onClose,
}: SimpleMigrationDialogProps) {
  const [issueNumber, setIssueNumber] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const validate = (): boolean => {
    setError(null)

    if (issueNumber.trim() === '') {
      setError('Please enter an issue number')
      return false
    }

    const num = parseInt(issueNumber, 10)
    if (isNaN(num)) {
      setError('Please enter a valid number')
      return false
    }

    if (num < 1) {
      setError('Issue number must be at least 1')
      return false
    }

    return true
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    if (!validate()) {
      return
    }

    onComplete(issueNumber)
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }

  return (
    <div
      className="migration-dialog__overlay"
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-labelledby="simple-migration-dialog-title"
    >
      <div className="migration-dialog">
        <div className="migration-dialog__header">
          <h2 id="simple-migration-dialog-title" className="migration-dialog__title">
            Track Issues for "{threadTitle}"
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="migration-dialog__close-btn"
            aria-label="Close dialog"
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} className="migration-dialog__form">
          <div className="migration-dialog__field">
            <label htmlFor="issue-number" className="migration-dialog__label">
              What issue number did you just read? <span className="migration-dialog__required">*</span>
            </label>
            <input
              ref={inputRef}
              id="issue-number"
              type="number"
              min="1"
              value={issueNumber}
              onChange={(e) => setIssueNumber(e.target.value)}
              placeholder="e.g., 42"
              className="migration-dialog__input"
            />
            <span className="migration-dialog__hint">
              We'll infer total issues from your remaining count
            </span>
          </div>

          {error && (
            <div className="migration-dialog__error" role="alert">
              {error}
            </div>
          )}

          <div className="migration-dialog__actions">
            <button
              type="submit"
              className="migration-dialog__btn migration-dialog__btn--primary"
            >
              Start Tracking
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
