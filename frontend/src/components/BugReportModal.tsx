import { useEffect, useState } from 'react'
import Modal from './Modal'
import { getApiErrorDetail } from '../utils/apiError'
import type { DiagnosticData } from '../hooks/useDiagnostics'

export type ReportType = 'bug' | 'feature'

interface BugReportModalProps {
  isOpen: boolean
  onClose: () => void
  onSubmit: (reportType: ReportType, title: string, description: string) => Promise<void>
  diagnosticData: DiagnosticData | null
}

export default function BugReportModal({
  isOpen,
  onClose,
  onSubmit,
  diagnosticData,
}: BugReportModalProps) {
  const [reportType, setReportType] = useState<ReportType>('bug')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setReportType('bug')
      setTitle('')
      setDescription('')
      setError(null)
      setIsSubmitting(false)
    }
  }, [isOpen])

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!title.trim() || !description.trim()) {
      setError('Title and description are required')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await onSubmit(reportType, title.trim(), description.trim())
    } catch (err) {
      console.error('Failed to submit report:', err)
      setError(getApiErrorDetail(err))
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDescriptionKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key !== 'Enter' ||
      event.shiftKey ||
      event.nativeEvent.isComposing ||
      isSubmitting ||
      !title.trim() ||
      !description.trim()
    ) {
      return
    }

    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  const isFeature = reportType === 'feature'

  return (
    <Modal
      isOpen={isOpen}
      title={isFeature ? 'Request a Feature' : 'Report a Bug'}
      onClose={onClose}
      overlayClassName="bug-report-modal__overlay"
      data-testid="bug-report-modal"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <p className="text-sm text-red-400">{error}</p>
          </div>
        )}

        <fieldset className="space-y-2">
          <legend className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
            What are you sending?
          </legend>
          <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Report type">
            {(['bug', 'feature'] as const).map((type) => (
              <label
                key={type}
                className={`cursor-pointer rounded-xl border px-3 py-3 text-center text-xs font-bold transition-colors focus-within:ring-2 focus-within:ring-[var(--theme-focus-ring)] focus-within:ring-offset-2 focus-within:ring-offset-[var(--theme-bg-page)] ${
                  reportType === type
                    ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-comic-accent)]/15 text-[var(--theme-comic-accent)]'
                    : 'border-[var(--theme-border)] bg-[var(--theme-bg-hover)] text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-hover)]'
                }`}
              >
                <input
                  type="radio"
                  name="report-type"
                  value={type}
                  checked={reportType === type}
                  onChange={() => setReportType(type)}
                  className="sr-only"
                />
                {type === 'bug' ? 'Bug report' : 'Feature request'}
              </label>
            ))}
          </div>
        </fieldset>

        <div className="space-y-2">
          <label htmlFor="report-title" className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
            Title
          </label>
          <input
            id="report-title"
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={isFeature ? 'Briefly describe the feature' : 'Briefly describe the bug'}
            className="w-full rounded-xl px-3 py-2 text-sm form-control"
            maxLength={200}
            required
          />
          <div className="text-[10px] text-[var(--theme-text-dim)] text-right">{title.length}/200 characters</div>
        </div>

        <div className="space-y-2">
          <label htmlFor="report-description" className="text-[10px] font-bold uppercase tracking-widest text-[var(--theme-text-dim)]">
            Description
          </label>
          <textarea
            id="report-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            onKeyDown={handleDescriptionKeyDown}
            enterKeyHint="send"
            placeholder={isFeature ? 'What would you like ComicPile to do, and how would it help?' : 'What were you doing, what happened, and what did you expect?'}
            className="w-full bg-[var(--theme-bg-hover)] border border-[var(--theme-border)] rounded-xl px-3 py-2 text-sm text-[var(--theme-text-primary)] min-h-[120px] resize-y focus:outline-none focus:ring-2 focus:ring-[var(--theme-focus-ring)]/50"
            rows={4}
            maxLength={2000}
            required
          />
          <div className="text-[10px] text-[var(--theme-text-dim)] text-right">{description.length}/2000 characters</div>
        </div>

        {diagnosticData && (
          <div className="text-[10px] text-[var(--theme-text-muted)] flex items-center gap-1">
            <span aria-hidden="true" className="text-[var(--theme-comic-accent)]">i</span>
            <span>Browser info and console errors will be included</span>
          </div>
        )}

        <p className="text-xs text-[var(--theme-text-muted)]" data-testid="bug-report-hourly-limit-notice">
          Non-admin accounts can submit one report per hour.
        </p>

        <div className="grid grid-cols-1 min-[360px]:grid-cols-2 gap-3 pt-2">
          <button type="button" onClick={onClose} disabled={isSubmitting} className="w-full py-3 bg-[var(--theme-bg-hover)] hover:bg-[var(--theme-bg-hover)] border border-[var(--theme-border)] rounded-xl text-[10px] font-black uppercase tracking-[0.1em] min-[360px]:tracking-[0.2em] transition-all disabled:opacity-50">
            Cancel
          </button>
          <button type="submit" disabled={isSubmitting || !title.trim() || !description.trim()} className="w-full py-3 bg-[var(--theme-comic-accent)]/20 hover:bg-[var(--theme-comic-accent)]/30 border border-[var(--theme-comic-accent)]/50 rounded-xl text-[10px] font-black uppercase tracking-[0.1em] min-[360px]:tracking-[0.2em] transition-all disabled:opacity-50">
            {isSubmitting ? 'Submitting...' : isFeature ? 'Submit Request' : 'Submit Report'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
