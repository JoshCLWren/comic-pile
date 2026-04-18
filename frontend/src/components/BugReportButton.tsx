import { useState } from 'react'
import BugReportModal from './BugReportModal'
import { useDiagnostics } from '../hooks/useDiagnostics'
import type { DiagnosticData } from '../hooks/useDiagnostics'
import { captureScreenshot } from '../utils/captureScreenshot'
import type { ScreenshotDiagnostics } from '../utils/captureScreenshot'
import { useBugReportRestore } from '../contexts/BugReportRestoreContext'

interface BugReportButtonProps {
  onSubmit: (title: string, description: string, screenshotBlob: Blob | null, diagnosticData: DiagnosticData | null, screenshotDiagnostics?: ScreenshotDiagnostics) => Promise<void>
  variant?: 'floating' | 'nav'
}

export default function BugReportButton({ onSubmit, variant = 'floating' }: BugReportButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [screenshotBlob, setScreenshotBlob] = useState<Blob | null>(null)
  const [diagnosticData, setDiagnosticData] = useState<DiagnosticData | null>(null)
  const [screenshotDiagnostics, setScreenshotDiagnostics] = useState<ScreenshotDiagnostics | null>(null)
  const { collectDiagnostics } = useDiagnostics()
  const { restoreLastView } = useBugReportRestore()

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
    restoreLastView()
  }

  return (
    <>
      <button
        onClick={handleClick}
        className={
          variant === 'nav'
            ? 'nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none hover:bg-white/5'
            : 'fixed bottom-20 right-4 z-50 flex items-center justify-center w-8 h-8 bg-stone-800/60 hover:bg-amber-500/80 text-stone-400 hover:text-stone-900 rounded-full shadow-sm transition-all backdrop-blur-sm'
        }
        aria-label="Report a bug"
        title="Report a bug"
        type="button"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={variant === 'nav' ? 'text-2xl mb-1' : 'w-4 h-4'}
          aria-hidden="true"
        >
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
        </svg>
        {variant === 'nav' ? (
          <span className="text-[10px] uppercase tracking-widest font-bold nav-label">Report</span>
        ) : null}
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
