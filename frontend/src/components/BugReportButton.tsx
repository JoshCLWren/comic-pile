import { useState } from 'react'
import BugReportModal from './BugReportModal'
import type { ReportType } from './BugReportModal'
import { useDiagnostics } from '../hooks/useDiagnostics'
import type { DiagnosticData } from '../hooks/useDiagnostics'
import { useBugReportRestore } from '../contexts/useBugReportRestore'

interface BugReportButtonProps {
  onSubmit: (
    reportType: ReportType,
    title: string,
    description: string,
    diagnosticData: DiagnosticData | null,
  ) => Promise<void>
  variant?: 'floating' | 'nav' | 'sidebar'
  collapsed?: boolean
}

export default function BugReportButton({
  onSubmit,
  variant = 'floating',
  collapsed = false,
}: BugReportButtonProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [diagnosticData, setDiagnosticData] = useState<DiagnosticData | null>(null)
  const { collectDiagnostics } = useDiagnostics()
  const { restoreLastView } = useBugReportRestore()

  const handleClick = () => {
    setDiagnosticData(collectDiagnostics())
    setIsModalOpen(true)
  }

  const handleClose = () => {
    setIsModalOpen(false)
    setDiagnosticData(null)
  }

  const handleSubmit = async (reportType: ReportType, title: string, description: string) => {
    await onSubmit(reportType, title, description, diagnosticData)
    handleClose()
    restoreLastView()
  }

  const isFloating = variant === 'floating'
  const isSidebar = variant === 'sidebar'
  const buttonClassName = isFloating
    ? 'fixed bottom-8 right-4 z-50 flex items-center justify-center w-8 h-8 bg-[var(--theme-bg-panel)] border-[var(--theme-border)] text-stone-400 hover:text-stone-900 rounded-full shadow-sm transition-all backdrop-blur-sm'
    : isSidebar
      ? collapsed
        ? 'flex h-8 w-8 items-center justify-center rounded-lg text-[var(--theme-text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]'
        : 'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-[var(--theme-text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--theme-text-primary)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--theme-focus-ring)]'
      : 'nav-item flex flex-col items-center justify-center flex-1 h-full transition-all duration-200 focus:outline-none hover:bg-white/5'

  return (
    <>
      <button
        onClick={handleClick}
        className={buttonClassName}
        aria-label="Send feedback"
        title="Send feedback"
        type="button"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          className={isFloating ? 'w-4 h-4' : isSidebar ? 'h-5 w-5' : 'text-2xl mb-1'}
          aria-hidden="true"
        >
          <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
        </svg>
        {!isFloating ? (
          <span
            className={
              isSidebar
                ? collapsed
                  ? 'hidden'
                  : 'text-sm font-medium'
                : 'text-[10px] uppercase tracking-widest font-bold nav-label'
            }
          >
            Feedback
          </span>
        ) : null}
      </button>

      <BugReportModal
        isOpen={isModalOpen}
        onClose={handleClose}
        onSubmit={handleSubmit}
        diagnosticData={diagnosticData}
      />
    </>
  )
}
