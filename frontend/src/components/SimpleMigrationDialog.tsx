import { useState } from 'react'
import Modal from './Modal'
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

  const validate = (): boolean => {
    setError(null)

    if (issueNumber.trim() === '') {
      setError('Please enter an issue number')
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

  return (
    <Modal isOpen title={`Track Issues for "${threadTitle}"`} onClose={onClose} data-testid="simple-migration-dialog">

        <form onSubmit={handleSubmit} className="migration-dialog__form">
          <div className="migration-dialog__field">
            <label htmlFor="issue-number" className="migration-dialog__label">
              What issue number did you just read? <span className="migration-dialog__required">*</span>
            </label>
            <input
              id="issue-number"
              type="text"
              value={issueNumber}
              onChange={(e) => setIssueNumber(e.target.value)}
              placeholder="e.g., 42"
              className="migration-dialog__input"
              autoFocus
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
    </Modal>
  )
}
