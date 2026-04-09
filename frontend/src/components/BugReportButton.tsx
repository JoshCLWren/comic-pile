import { useState } from 'react'
import { toBlob } from 'html-to-image'
import BugReportModal from './BugReportModal'

interface BugReportButtonProps {
  onSubmit: (title: string, description: string, screenshotBlob: Blob | null) => Promise<void>
}

export default function BugReportButton({ onSubmit }: BugReportButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [screenshotBlob, setScreenshotBlob] = useState<Blob | null>(null)

  const handleClick = async () => {
    try {
      const blob = await toBlob(document.body, { skipFonts: true })
      setScreenshotBlob(blob)
    } catch (error) {
      console.error('Failed to capture screenshot:', error)
      setScreenshotBlob(null)
    } finally {
      setIsModalOpen(true)
    }
  }

  const handleClose = () => {
    setIsModalOpen(false)
    setScreenshotBlob(null)
  }

  const handleSubmit = async (title: string, description: string, screenshotBlob: Blob | null) => {
    await onSubmit(title, description, screenshotBlob)
    handleClose()
  }

  return (
    <>
      <button
        onClick={handleClick}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-stone-900 rounded-lg shadow-lg transition-all hover:scale-105"
        aria-label="Report a bug"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="currentColor"
          className="w-5 h-5"
        >
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
        </svg>
        <span className="text-sm font-semibold">Report Bug</span>
      </button>

      <BugReportModal
        isOpen={isModalOpen}
        onClose={handleClose}
        screenshotBlob={screenshotBlob}
        onSubmit={handleSubmit}
      />
    </>
  )
}
