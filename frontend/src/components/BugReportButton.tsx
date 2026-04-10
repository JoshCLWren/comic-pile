import { useState } from 'react'
import BugReportModal from './BugReportModal'
import { useDiagnostics } from '../hooks/useDiagnostics'
import type { DiagnosticData } from '../hooks/useDiagnostics'
import { captureScreenshot } from '../utils/captureScreenshot'

interface BugReportButtonProps {
  onSubmit: (title: string, description: string, screenshotBlob: Blob | null, diagnosticData: DiagnosticData | null) => Promise<void>
}

const SCREENSHOT_TIMEOUT_MS = 8000

export default function BugReportButton({ onSubmit }: BugReportButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isCapturing, setIsCapturing] = useState(false)
  const [screenshotBlob, setScreenshotBlob] = useState<Blob | null>(null)
  const [diagnosticData, setDiagnosticData] = useState<DiagnosticData | null>(null)
  const { collectDiagnostics } = useDiagnostics()

  const handleClick = async () => {
    const diagnostics = collectDiagnostics()
    setDiagnosticData(diagnostics)
    setIsCapturing(true)
    // Capture screenshot BEFORE opening modal — the modal's dark backdrop
    // covers the viewport and would make every screenshot appear blank.
    try {
      const blob = await Promise.race([
        captureScreenshot(),
        new Promise<null>(resolve => setTimeout(() => resolve(null), SCREENSHOT_TIMEOUT_MS)),
      ])
      setScreenshotBlob(blob)
    } catch (error) {
      console.error('Failed to capture screenshot:', error)
      setScreenshotBlob(null)
    } finally {
      setIsCapturing(false)
      setIsModalOpen(true)
    }
  }

  const handleClose = () => {
    setIsModalOpen(false)
    setScreenshotBlob(null)
    setDiagnosticData(null)
  }

  const handleSubmit = async (title: string, description: string, screenshotBlob: Blob | null) => {
    await onSubmit(title, description, screenshotBlob, diagnosticData)
    handleClose()
  }

  return (
    <>
      <button
        onClick={handleClick}
        disabled={isCapturing}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-stone-900 rounded-lg shadow-lg transition-all hover:scale-105 disabled:opacity-70 disabled:cursor-wait disabled:hover:scale-100"
        aria-label={isCapturing ? 'Capturing screenshot…' : 'Report a bug'}
      >
        {isCapturing ? (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            className="w-5 h-5 animate-spin"
          >
            <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
            <path d="M12 2a10 10 0 0 1 10 10" />
          </svg>
        ) : (
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="currentColor"
            className="w-5 h-5"
          >
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
          </svg>
        )}
        <span className="text-sm font-semibold">{isCapturing ? 'Capturing…' : 'Report Bug'}</span>
      </button>

      <BugReportModal
        isOpen={isModalOpen}
        onClose={handleClose}
        screenshotBlob={screenshotBlob}
        onSubmit={handleSubmit}
        diagnosticData={diagnosticData}
      />
    </>
  )
}
