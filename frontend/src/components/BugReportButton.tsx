import { useState } from 'react'
import BugReportModal from './BugReportModal'
import { useDiagnostics } from '../hooks/useDiagnostics'
import type { DiagnosticData } from '../hooks/useDiagnostics'
import { captureScreenshot } from '../utils/captureScreenshot'
import type { ScreenshotDiagnostics } from '../utils/captureScreenshot'

interface BugReportButtonProps {
  onSubmit: (title: string, description: string, screenshotBlob: Blob | null, diagnosticData: DiagnosticData | null, screenshotDiagnostics?: ScreenshotDiagnostics) => Promise<void>
}

export default function BugReportButton({ onSubmit }: BugReportButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [screenshotBlob, setScreenshotBlob] = useState<Blob | null>(null)
  const [diagnosticData, setDiagnosticData] = useState<DiagnosticData | null>(null)
  const [screenshotDiagnostics, setScreenshotDiagnostics] = useState<ScreenshotDiagnostics | null>(null)
  const { collectDiagnostics } = useDiagnostics()

  const handleClick = async () => {
    const diagnostics = collectDiagnostics()
    setDiagnosticData(diagnostics)

    try {
      const result = await captureScreenshot()
      setScreenshotBlob(result.blob)
      setScreenshotDiagnostics(result.diagnostics)
    } catch (error) {
      console.error('Failed to capture screenshot:', error)
      setScreenshotBlob(null)
      setScreenshotDiagnostics(null)
    } finally {
      setIsModalOpen(true)
}
  }

  const handleClose = () => {
    setIsModalOpen(false)
    setScreenshotBlob(null)
    setDiagnosticData(null)
    setScreenshotDiagnostics(null)
  }

  const handleSubmit = async (title: string, description: string, screenshotBlob: Blob | null) => {
    await onSubmit(title, description, screenshotBlob, diagnosticData, screenshotDiagnostics ?? undefined)
    handleClose()
  }

  return (
    <>
      <button
        onClick={handleClick}
        className="fixed bottom-20 right-4 z-50 flex items-center justify-center w-8 h-8 bg-stone-800/60 hover:bg-amber-500/80 text-stone-400 hover:text-stone-900 rounded-full shadow-sm transition-all backdrop-blur-sm"
        aria-label="Report a bug"
        title="Report a bug"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className="w-4 h-4"
        >
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
        </svg>
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
