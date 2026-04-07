import { useState, useEffect } from 'react'
import Modal from './Modal'

interface BugReportModalProps {
  isOpen: boolean
  onClose: () => void
  screenshotBlob: Blob | null
  onSubmit: (title: string, description: string, screenshotBlob: Blob | null) => Promise<void>
}

export default function BugReportModal({
  isOpen,
  onClose,
  screenshotBlob,
  onSubmit,
}: BugReportModalProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [screenshotUrl, setScreenshotUrl] = useState<string | null>(null)
  const [activeBlob, setActiveBlob] = useState<Blob | null>(screenshotBlob)

  useEffect(() => {
    setActiveBlob(screenshotBlob)
    if (screenshotBlob) {
      const url = URL.createObjectURL(screenshotBlob)
      setScreenshotUrl(url)
      return () => {
        URL.revokeObjectURL(url)
      }
    } else {
      setScreenshotUrl(null)
    }
  }, [screenshotBlob])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !description.trim()) {
      setError('Title and description are required')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await onSubmit(title.trim(), description.trim(), activeBlob)
      setTitle('')
      setDescription('')
      onClose()
    } catch (err) {
      console.error('Failed to submit bug report:', err)
      setError(err instanceof Error ? err.message : 'Failed to submit bug report')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleClearScreenshot = () => {
    if (screenshotUrl) {
      URL.revokeObjectURL(screenshotUrl)
      setScreenshotUrl(null)
    }
    setActiveBlob(null)
  }

  return (
    <Modal
      isOpen={isOpen}
      title="Report a Bug"
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

        <div className="space-y-2">
          <label htmlFor="bug-title" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Title
          </label>
          <input
            id="bug-title"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Brief description of the bug"
            className="w-full bg-white/5 border border-stone-700 rounded-xl px-3 py-2 text-sm text-stone-200 focus:outline-none focus:ring-2 focus:ring-amber-500/50"
            maxLength={200}
            required
          />
          <div className="text-[10px] text-stone-500 text-right">
            {title.length}/200 characters
          </div>
        </div>

        <div className="space-y-2">
          <label htmlFor="bug-description" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Description
          </label>
          <textarea
            id="bug-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Please describe what you were doing when the bug occurred..."
            className="w-full bg-white/5 border border-stone-700 rounded-xl px-3 py-2 text-sm text-stone-200 min-h-[120px] resize-y focus:outline-none focus:ring-2 focus:ring-amber-500/50"
            rows={4}
            maxLength={2000}
            required
          />
          <div className="text-[10px] text-stone-500 text-right">
            {description.length}/2000 characters
          </div>
        </div>

        {screenshotUrl && (
          <div className="space-y-2">
            <label className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
              Screenshot
            </label>
            <div className="relative">
              <img
                src={screenshotUrl}
                alt="Screenshot"
                className="w-full max-h-48 object-contain border border-stone-700 rounded-xl"
              />
              <button
                type="button"
                onClick={handleClearScreenshot}
                className="mt-2 text-[10px] text-amber-500 hover:text-amber-400 transition-colors"
              >
                Clear screenshot
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting || !title.trim() || !description.trim()}
            className="w-full py-3 bg-amber-600/20 hover:bg-amber-600/30 border border-amber-600/50 rounded-xl text-[10px] font-black uppercase tracking-[0.2em] transition-all disabled:opacity-50"
          >
            {isSubmitting ? 'Submitting...' : 'Submit Report'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
