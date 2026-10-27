import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { ReadingBoundaryExplanation } from '../components/ReadingBoundaryExplanation'
import type {
  BoundaryEditorTarget,
  BoundaryIssue,
  ReadingBoundaryExplanation as Explanation,
} from '../services/api-reading-boundaries'

function issue(overrides: Partial<BoundaryIssue> = {}): BoundaryIssue {
  return {
    issue_id: 9,
    thread_id: 2,
    thread_title: 'One Year In',
    issue_number: '1',
    label: 'One Year In #1',
    volume_label: 'One Year In (2025)',
    ...overrides,
  }
}

function explanation(overrides: Partial<Explanation> = {}): Explanation {
  return {
    thread_id: 1,
    state: 'available',
    summary: 'Saga #6 is available next.',
    ...overrides,
  }
}

function renderExplanation(props: Parameters<typeof ReadingBoundaryExplanation>[0]) {
  return render(
    <MemoryRouter>
      <ReadingBoundaryExplanation {...props} />
    </MemoryRouter>,
  )
}

describe('ReadingBoundaryExplanation', () => {
  it('shows a status while the canonical read is pending', () => {
    renderExplanation({ isPending: true })
    expect(screen.getByRole('status')).toHaveTextContent('Loading reading boundaries…')
  })

  it('shows a recoverable error and calls the retry handler', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    renderExplanation({ isError: true, onRetry })

    expect(screen.getByRole('alert')).toHaveTextContent('Reading boundaries could not be loaded.')
    await user.click(screen.getByRole('button', { name: 'Retry reading boundaries' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('falls back to the supplied legacy content when the evaluator is unavailable', () => {
    renderExplanation({
      explanation: explanation({ state: 'unavailable', summary: 'Option E is not active.' }),
      fallback: <p>Legacy recorded prerequisites</p>,
    })

    expect(screen.queryByTestId('canonical-reading-boundary')).not.toBeInTheDocument()
    expect(screen.getByText('Legacy recorded prerequisites')).toBeInTheDocument()
  })

  it('renders the neutral unavailable copy without a fallback', () => {
    renderExplanation({ explanation: explanation({ state: 'unavailable' }) })
    expect(screen.getByText('Reading boundaries are unavailable.')).toBeInTheDocument()
  })

  it('renders multiple canonical blockers without legacy associations', () => {
    renderExplanation({
      explanation: explanation({
        state: 'blocked',
        summary: 'Saga #6 is waiting on 2 live requirements.',
        blockers: [
          {
            kind: 'hold',
            origin: 'reading_list',
            reason: 'Hold in Ultimate: waiting on One Year In #1',
            waiting_on: [issue()],
            editor: { kind: 'reading_list', list_id: 4, label: 'Ultimate' },
          },
          {
            kind: 'prerequisite',
            origin: 'reader_prerequisite',
            reason: 'Finish the previous issue first.',
            editor: { kind: 'prerequisite', thread_id: 1, label: 'Saga prerequisites' },
          },
        ],
      }),
    })

    const blockerList = screen.getByRole('list', { name: 'Active reading blockers' })
    expect(blockerList).toHaveTextContent('Hold in Ultimate: waiting on One Year In #1')
    expect(blockerList).toHaveTextContent('Finish the previous issue first.')
    expect(screen.getByRole('link', { name: 'Open One Year In issue #1' })).toHaveAttribute(
      'href',
      '/thread/2?issue=9#issue-9',
    )
    expect(screen.getByRole('link', { name: 'Edit Ultimate' })).toHaveAttribute(
      'href',
      '/reading-lists/4',
    )
    expect(within(blockerList).getByRole('link', { name: 'Edit Saga prerequisites' })).toHaveAttribute(
      'href',
      '/thread/1?prerequisites=1',
    )
    expect(screen.queryByText('Historical associations — not active blockers')).not.toBeInTheDocument()
  })

  it('shows only the first actionable strict-order issue by default in compact mode', async () => {
    renderExplanation({
      compact: true,
      explanation: explanation({
        state: 'blocked',
        summary: 'Abe Sapien #8 is waiting on strict Mignolaverse order.',
        blockers: [{
          kind: 'strict_order',
          origin: 'reading_list',
          reason: 'Strict order in Mignolaverse: read Casualties #1 and every other earlier unread comic first',
          waiting_on: [
            issue({ issue_id: 117305, thread_id: 18847, thread_title: 'B.P.R.D.: Casualties', label: 'B.P.R.D.: Casualties #1' }),
            issue({ issue_id: 117306, thread_id: 18848, thread_title: 'Abe Sapien: The Haunted Boy', label: 'Abe Sapien: The Haunted Boy #1' }),
          ],
        }],
      }),
    })
    const first = screen.getByRole('link', { name: 'Open B.P.R.D.: Casualties issue #1' })
    expect(first).toBeVisible()
    const disclosure = screen.getByRole('button', { name: 'Show all reading requirements' })
    expect(disclosure).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Open Abe Sapien: The Haunted Boy issue #1' })).not.toBeInTheDocument()
    expect(first.closest('p')).toHaveTextContent(/^Read B\.P\.R\.D\.: Casualties #1.* first\.$/)
    await userEvent.setup().click(disclosure)
    expect(screen.getByRole('button', { name: 'Hide all reading requirements' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Open Abe Sapien: The Haunted Boy issue #1' })).toBeVisible()
  })

  it('links the next issue to its editor target when the server supplies one', () => {
    renderExplanation({
      explanation: explanation({
        next: {
          issue: issue({ issue_id: 12, thread_id: 3, thread_title: 'Saga', issue_number: '7', label: 'Saga #7', volume_label: null }),
          editor: { kind: 'issue', thread_id: 3, issue_id: 12, label: 'Saga #7' },
        },
      }),
    })

    expect(screen.getByRole('link', { name: 'Open Saga issue #7' })).toHaveAttribute(
      'href',
      '/thread/3?issue=12#issue-12',
    )
    expect(screen.getByRole('link', { name: 'Edit Saga #7' })).toHaveAttribute(
      'href',
      '/thread/3?issue=12#issue-12',
    )
  })

  it('omits the next block when the evaluator has no next issue', () => {
    renderExplanation({ explanation: explanation({ next: null }) })
    expect(screen.queryByText(/^Next:/)).not.toBeInTheDocument()
  })

  it('appends a volume label only when the issue label does not already carry it', () => {
    renderExplanation({
      explanation: explanation({
        state: 'blocked',
        blockers: [
          {
            kind: 'hold',
            origin: 'reading_list',
            reason: 'Hold in Ultimate.',
            waiting_on: [
              issue({ label: 'One Year In #1', volume_label: 'One Year In' }),
              issue({ issue_id: 10, issue_number: '2', label: 'One Year In #2', volume_label: 'One Year In (2025)' }),
            ],
          },
        ],
      }),
    })

    expect(screen.getByRole('link', { name: 'Open One Year In issue #1' })).toHaveTextContent(
      'One Year In #1',
    )
    expect(screen.getByRole('link', { name: 'Open One Year In issue #1' })).not.toHaveTextContent(
      'One Year In #1 · One Year In',
    )
    expect(screen.getByRole('link', { name: 'Open One Year In issue #2' })).toHaveTextContent(
      'One Year In #2 · One Year In (2025)',
    )
  })

  it('skips an editor link whose descriptor has no routable target', () => {
    const unroutable: BoundaryEditorTarget = { kind: 'issue', label: 'Detached issue' }
    renderExplanation({
      explanation: explanation({
        state: 'blocked',
        blockers: [
          {
            kind: 'prerequisite',
            origin: 'reader_prerequisite',
            reason: 'Finish the previous issue first.',
            editor: unroutable,
          },
        ],
      }),
    })

    expect(screen.queryByRole('link', { name: 'Edit Detached issue' })).not.toBeInTheDocument()
  })
})
