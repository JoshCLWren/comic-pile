import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import BugReportModal from '../components/BugReportModal'

it('states the non-admin hourly limit and shows when the user can submit again', async () => {
  const user = userEvent.setup()
  const detail =
    'Non-admin accounts can submit one GitHub issue per hour. ' +
    'Try again in 42 minute(s), after 2026-10-18 15:04 UTC.'
  const onSubmit = vi
    .fn()
    .mockRejectedValue({ response: { status: 429, data: { detail } } })

  render(
    <BugReportModal
      isOpen
      onClose={vi.fn()}
      onSubmit={onSubmit}
      diagnosticData={null}
    />,
  )

  expect(screen.getByTestId('bug-report-hourly-limit-notice')).toHaveTextContent(
    'one report per hour',
  )

  await user.type(screen.getByLabelText('Title'), 'A title')
  await user.type(screen.getByLabelText('Description'), 'A description')
  await user.click(screen.getByRole('button', { name: /submit report/i }))

  await waitFor(() => {
    expect(
      screen.getByText(
        /Non-admin accounts can submit one GitHub issue per hour\. Try again in \d+ minute\(s\), after \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC/,
      ),
    ).toBeInTheDocument()
  })
})
