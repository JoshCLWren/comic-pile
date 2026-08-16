import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import BugReportModal from '../components/BugReportModal'
import type { DiagnosticData } from '../hooks/useDiagnostics'

const dummyDiagnostics: DiagnosticData = {
  timestamp: '2024-01-01T00:00:00.000Z',
  url: 'http://test.com/queue',
  userAgent: 'test-agent',
  screen: { width: 1920, height: 1080, pixelRatio: 1 },
  viewport: { width: 1920, height: 1080 },
  scroll: { x: 0, y: 0 },
  performance: { domContentLoaded: 1000, loadComplete: 2000 },
  errors: [{ message: 'test error', timestamp: '2024-01-01T00:00:00.000Z' }],
}

it('renders the diagnostic notice with the expected wording when diagnostics are available', () => {
  const onClose = vi.fn()
  const onSubmit = vi.fn().mockResolvedValue(undefined)

  render(
    <BugReportModal
      isOpen
      onClose={onClose}
      onSubmit={onSubmit}
      diagnosticData={dummyDiagnostics}
    />,
  )

  const dialog = screen.getByRole('dialog', { name: 'Report a Bug' })
  expect(dialog).toBeInTheDocument()

  // Regression guard for issue #1306: the notice must mention "browser info & console errors"
  expect(
    screen.getByText(/browser info & console errors/i),
  ).toBeInTheDocument()
  expect(
    screen.getByText(/browser info & console errors/i),
  ).toBeVisible()
})

it('does not render the diagnostic notice when no diagnostics are provided', () => {
  render(
    <BugReportModal
      isOpen
      onClose={vi.fn()}
      onSubmit={vi.fn().mockResolvedValue(undefined)}
      diagnosticData={null}
    />,
  )

  expect(screen.queryByText(/browser info/i)).not.toBeInTheDocument()
})

it('resets the form fields when reopened', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn().mockResolvedValue(undefined)
  const onClose = vi.fn()

  const { rerender } = render(
    <BugReportModal
      isOpen
      onClose={onClose}
      onSubmit={onSubmit}
      diagnosticData={dummyDiagnostics}
    />,
  )

  const titleInput = screen.getByLabelText('Title')
  const descriptionInput = screen.getByLabelText('Description')

  await user.type(titleInput, 'A bug')
  await user.type(descriptionInput, 'Something broke')

  expect(titleInput).toHaveValue('A bug')
  expect(descriptionInput).toHaveValue('Something broke')

  rerender(
    <BugReportModal
      isOpen={false}
      onClose={onClose}
      onSubmit={onSubmit}
      diagnosticData={dummyDiagnostics}
    />,
  )

  rerender(
    <BugReportModal
      isOpen
      onClose={onClose}
      onSubmit={onSubmit}
      diagnosticData={dummyDiagnostics}
    />,
  )

  expect(screen.getByLabelText('Title')).toHaveValue('')
  expect(screen.getByLabelText('Description')).toHaveValue('')
})
