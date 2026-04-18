import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import BugReportButton from '../components/BugReportButton'

const captureScreenshotMock = vi.hoisted(() => vi.fn())
const collectDiagnosticsMock = vi.hoisted(() => vi.fn())
const restoreLastViewMock = vi.hoisted(() => vi.fn())

vi.mock('../utils/captureScreenshot', () => ({
  captureScreenshot: captureScreenshotMock,
}))

vi.mock('../hooks/useDiagnostics', () => ({
  useDiagnostics: () => ({ collectDiagnostics: collectDiagnosticsMock }),
}))

vi.mock('../contexts/BugReportRestoreContext', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
    restoreLastView: restoreLastViewMock,
  }),
}))

vi.mock('../components/BugReportModal', () => ({
  default: ({ isOpen, onSubmit }: { isOpen: boolean; onSubmit: (title: string, description: string, screenshotBlob: Blob | null) => Promise<void> }) =>
    isOpen ? (
      <div role="dialog" aria-label="Report a Bug">
        <button type="button" onClick={() => onSubmit('Bug title', 'Bug description', null)}>
          Submit Report
        </button>
      </div>
    ) : null,
}))

describe('BugReportButton', () => {
  beforeEach(() => {
    captureScreenshotMock.mockResolvedValue({ blob: new Blob(['png'], { type: 'image/png' }), diagnostics: {} })
    collectDiagnosticsMock.mockReturnValue({ timestamp: '2024-01-01T00:00:00.000Z' })
    restoreLastViewMock.mockReset()
  })

  it('restores the prior view after a successful bug submission', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(<BugReportButton onSubmit={onSubmit} />)

    await user.click(screen.getByRole('button', { name: /report a bug/i }))
    await user.click(await screen.findByRole('button', { name: /submit report/i }))

    expect(onSubmit).toHaveBeenCalledWith(
      'Bug title',
      'Bug description',
      null,
      { timestamp: '2024-01-01T00:00:00.000Z' },
      {},
    )
    expect(restoreLastViewMock).toHaveBeenCalledTimes(1)
  })
})
