import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import BugReportButton from '../components/BugReportButton'
import type { ReportType } from '../components/BugReportModal'

const collectDiagnostics = vi.fn(() => ({ route: '/queue' }))
const restoreLastView = vi.fn()

vi.mock('../hooks/useDiagnostics', () => ({ useDiagnostics: () => ({ collectDiagnostics }) }))
vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({ restoreLastView }),
}))
vi.mock('../components/BugReportModal', () => ({
  default: ({ isOpen, onClose, onSubmit, diagnosticData }: {
    isOpen: boolean
    onClose: () => void
    onSubmit: (reportType: ReportType, title: string, description: string) => Promise<void>
    diagnosticData: unknown
  }) => isOpen ? <div><span>{JSON.stringify(diagnosticData)}</span><button onClick={onClose}>Close report</button><button onClick={() => void onSubmit('feature', 'Title', 'Description')}>Submit report</button></div> : null,
}))

it('collects diagnostics, submits them, restores the view, and closes the dialog', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  render(<BugReportButton onSubmit={onSubmit} />)

  await user.click(screen.getByRole('button', { name: 'Send feedback' }))
  expect(screen.getByText('{"route":"/queue"}')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Submit report' }))

  expect(onSubmit).toHaveBeenCalledWith('feature', 'Title', 'Description', { route: '/queue' })
  expect(restoreLastView).toHaveBeenCalledOnce()
  expect(screen.queryByRole('button', { name: 'Submit report' })).not.toBeInTheDocument()
})

it('renders the navigation variant and closes without submitting', async () => {
  const user = userEvent.setup()
  render(<BugReportButton onSubmit={vi.fn()} variant="nav" />)

  expect(screen.getByText('Feedback')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Send feedback' }))
  await user.click(screen.getByRole('button', { name: 'Close report' }))
  expect(screen.queryByRole('button', { name: 'Submit report' })).not.toBeInTheDocument()
})
