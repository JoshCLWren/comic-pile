import { useState } from 'react'
import Modal from './Modal'

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
    <Modal
      isOpen
      title={`Track Issues for "${threadTitle}"`}
      onClose={onClose}
      data-testid="simple-migration-dialog"
      autoFocus={true}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <label htmlFor="issue-number" className="block text-sm font-semibold text-[var(--theme-text-primary)]">
            What issue number did you just read? <span className="text-[var(--theme-error)]" aria-hidden="true">*</span>
          </label>
          <input
            id="issue-number"
            type="text"
            value={issueNumber}
            onChange={(e) => setIssueNumber(e.target.value)}
            placeholder="e.g., 42"
            className="form-control w-full"
            autoFocus
          />
          <span className="text-xs text-[var(--theme-text-muted)]">
            We'll infer total issues from your remaining count
          </span>
        </div>

        {error && (
          <div className="rounded-lg border border-[color-mix(in_srgb,_var(--theme-error)_30%,_transparent)] bg-[color-mix(in_srgb,_var(--theme-error)_20%,_transparent)] p-3" role="alert">
            <p className="text-sm text-[var(--theme-error)]">{error}</p>
          </div>
        )}

        <div className="flex justify-end pt-2">
          <button
            type="submit"
            className="px-5 py-2.5 text-sm font-semibold rounded-lg transition-colors text-white bg-[var(--theme-primary-action)] hover:bg-[var(--theme-primary-action-hover)]"
          >
            Start Tracking
          </button>
        </div>
      </form>
    </Modal>
  )
}