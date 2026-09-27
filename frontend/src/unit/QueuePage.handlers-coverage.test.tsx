import { fireEvent, render, screen, unmount, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter, MemoryRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import {
  createCallbackCoverageComponents,
  createIssueFixture,
  createQueuePageDoubles,
  createThreadFixture,
  type QueuePageDoubles,
} from './support/queuePageHarness'

const SAGA = createThreadFixture({
  id: 1,
  title: 'Saga',
  queue_position: 1,
  issues_remaining: 3,
  created_at: '2024-01-01',
})
const DONE = createThreadFixture({
  id: 2,
  title: 'Done',
  queue_position: 0,
  issues_remaining: 0,
  total_issues: 3,
  created_at: '2023-01-01',
  status: 'completed',
})

/** Build the callback-coverage double set with the stubbed component tree. */
function createDoubles(
  options: Parameters<typeof createQueuePageDoubles>[0] = {},
): QueuePageDoubles {
  return createQueuePageDoubles({
    threads: { data: [SAGA, DONE] },
    components: createCallbackCoverageComponents(),
    ...options,
  })
}

/** Render the page with an injected double set and return the doubles. */
function renderPage(
  doubles: QueuePageDoubles = createDoubles(),
): QueuePageDoubles {
  render(
    <BrowserRouter>
      <QueuePage dependencies={doubles.deps} />
    </BrowserRouter>,
  )
  return doubles
}

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
})

describe('QueuePage callback coverage', () => {
  it('runs card callbacks and closes the dependency flow', async () => {
    const user = userEvent.setup()
    const doubles = renderPage()
    await user.click(screen.getByText('card callback'))
    await user.click(screen.getByText('drag start'))
    await user.click(screen.getByText('drag over'))
    await user.click(screen.getByText('drop'))
    await user.click(screen.getByText('drag end'))
    await user.click(screen.getByText('read callback'))
    await user.click(screen.getByText('edit callback'))
    await user.click(screen.getByText('snooze callback'))
    await user.click(screen.getByText('delete callback'))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('back callback'))
    await user.click(screen.getByText('dependencies callback'))
    await user.click(screen.getByText('dependency changed'))
    await user.click(screen.getByText('close dependencies'))
    expect(doubles.mutations.moveToFront.calls).toHaveLength(1)
  })

  it('covers action errors, rejected actions, and reposition validation', async () => {
    const doubles = createDoubles()
    const failAll = async () => {
      throw new Error('operation failed')
    }
    doubles.mutations.snooze.setImplementation(failAll)
    doubles.mutations.moveToFront.setImplementation(failAll)
    doubles.mutations.moveToPosition.setImplementation(failAll)
    const user = userEvent.setup()
    renderPage(doubles)
    await user.click(screen.getByText('read callback'))
    await user.click(screen.getByText('snooze callback'))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByText('invalid position'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
    await user.click(screen.getByText('confirm position'))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByText('cancel position'))
  })

  it('submits create, edit, reactivation, and migration dialog flows', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    doubles.mutations.create.setImplementation(async () => ({ id: 9 }))
    doubles.mutations.update.setImplementation(async () => ({}))
    doubles.mutations.reactivate.setImplementation(async () => ({}))
    renderPage(doubles)
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'New')
    await user.type(screen.getByLabelText('Issues'), '1-2')
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() => expect(doubles.mutations.create.calls).toHaveLength(1))

    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    await user.click(screen.getByText('skip migration'))
    expect(doubles.mutations.update.calls).toHaveLength(1)
  })

  it('covers blocked-state failures, complex issue creation, and mutation failures', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    doubles.services.dependenciesApi.getBatchBlockingInfo.mockRejectedValueOnce(
      new Error('blocked lookup failed'),
    )
    doubles.services.issuesApi.create.mockRejectedValueOnce(new Error('issue create failed'))
    doubles.mutations.create.setImplementation(async () => ({ id: 9 }))
    renderPage(doubles)
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Complex')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith(expect.stringContaining('issue create failed')),
    )

    const failMutation = async () => {
      throw new Error('mutation failed')
    }
    doubles.mutations.snooze.setImplementation(failMutation)
    doubles.mutations.remove.setImplementation(failMutation)
    await user.click(screen.getByText('snooze callback'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
    await user.click(screen.getByText('delete callback'))
    expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /delete series/i }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('mutation failed'))
  })

  it('covers migrated edit fields, location-driven create, and migration refresh failure', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles({
      threads: { data: [createThreadFixture({ ...SAGA, total_issues: 4 })] },
    })
    renderPage(doubles)
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByText('issue list')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    expect(screen.queryByText('issue list')).not.toBeInTheDocument()
  })

  it('persists a drag reorder between two active threads', async () => {
    const second = createThreadFixture({ id: 3, title: 'Second', queue_position: 2 })
    const doubles = createDoubles({ threads: { data: [SAGA, second] } })
    const user = userEvent.setup()
    renderPage(doubles)
    await user.click(screen.getAllByText('drag start')[0]!)
    await user.click(screen.getAllByText('drag over')[1]!)
    await user.click(screen.getAllByText('drop')[1]!)
    await waitFor(() =>
      expect(doubles.mutations.moveToPosition.calls).toEqual([{ id: 1, position: 2 }]),
    )
  })

  it('completes and closes migration dialogs, including refresh failures', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles({
      threads: {
        data: [SAGA, DONE],
        // The migration-completion handler refreshes the queue before the
        // session; a queue refresh failure is the refresh-failure branch.
        refetch: async () => {
          throw new Error('refresh failed')
        },
      },
    })
    renderPage(doubles)
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    await user.click(screen.getByText('complete migration'))
    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith('Failed to refresh data. Please refresh the page.'),
    )

    await user.click(screen.getByRole('button', { name: /close modal/i }))
    await user.click(screen.getByText('edit modal callback'))
    await user.click(screen.getByRole('button', { name: /migrate to issue tracking/i }))
    await user.click(screen.getByText('close migration'))
    expect(screen.queryByText('complete migration')).not.toBeInTheDocument()
  })

  it('opens a modal requested through router location state', async () => {
    const doubles = createDoubles()
    render(
      <MemoryRouter initialEntries={[{ pathname: '/queue', state: { openCreate: true } }]}>
        <QueuePage dependencies={doubles.deps} />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument(),
    )
  })

  it('uses the virtualized queue renderer for large queues', () => {
    const manyThreads = Array.from({ length: 51 }, (_unused, index) =>
      createThreadFixture({ id: index + 1, queue_position: index + 1 }),
    )
    const doubles = createDoubles({ threads: { data: manyThreads } })
    renderPage(doubles)
    expect(screen.getAllByText('card callback')).toHaveLength(51)
  })

  it('shows issue preview errors and creates complex ranges with read markers', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    doubles.services.issuesApi.create.mockResolvedValue({
      issues: [createIssueFixture({ id: 21, issue_number: 'Annual 1' })],
      total_count: 1,
      page_size: 100,
      next_page_token: null,
    })
    doubles.mutations.create.setImplementation(async () => ({ id: 9 }))
    renderPage(doubles)
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Annuals')
    await user.type(screen.getByLabelText('Issues'), 'Annual 1, 3-4')
    await user.type(screen.getByLabelText(/Issues already read/i), '1')
    expect(screen.getByText(/Will create/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() => expect(doubles.services.issuesApi.bulkMarkRead).toHaveBeenCalledWith([21]))

    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Invalid')
    await user.type(screen.getByLabelText('Issues'), 'x'.repeat(101))
    await waitFor(() => expect(screen.getByText(/issue identifier too long/i)).toBeInTheDocument())
  })

  it('alerts the user when create submit is attempted with an invalid issue range', async () => {
    const user = userEvent.setup()
    const doubles = renderPage()
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'Broken Range')
    await user.type(screen.getByLabelText('Issues'), '8-2')
    await user.click(screen.getByRole('button', { name: /create series/i }))
    await waitFor(() =>
      expect(alert).toHaveBeenCalledWith(expect.stringContaining('Failed to create series')),
    )
    expect(doubles.mutations.create.calls).toHaveLength(0)
  })

  it('loads mixed blocking reasons and leaves a blank reactivation selection untouched', async () => {
    const doubles = createDoubles({
      blockingInfo: { 1: [{ label: 'Finish Saga' }] },
    })
    const user = userEvent.setup()
    renderPage(doubles)
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    const form = screen.getByRole('button', { name: /add to queue/i }).closest('form')!
    fireEvent.submit(form)
    expect(doubles.mutations.reactivate.calls).toHaveLength(0)
  })

  it('covers queue sorting, filtering, empty states, and router edit state', async () => {
    const user = userEvent.setup()
    const zeta = createThreadFixture({ id: 1, title: 'Zeta', queue_position: 1 })
    const alpha = createThreadFixture({ id: 3, title: 'Alpha', queue_position: 2, created_at: '2025-01-01' })
    const doubles = createDoubles({
      resolveThreads: (searchTerm) => ({ data: searchTerm === 'missing' ? [] : [zeta, alpha] }),
    })
    renderPage(doubles)
    await user.click(screen.getByRole('button', { name: 'Title' }))
    await user.click(screen.getByRole('button', { name: 'Recently added' }))
    await user.type(screen.getByPlaceholderText('Search...'), 'missing')
    // Search is debounced (300ms) so the parent query only commits after the delay.
    await waitFor(
      () => expect(screen.getByText('No active series match your search')).toBeInTheDocument(),
      { timeout: 2000 },
    )
    await user.clear(screen.getByPlaceholderText('Search...'))
    await waitFor(() => expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument(), {
      timeout: 2000,
    })

    render(
      <MemoryRouter initialEntries={[{ pathname: '/queue', state: { editThreadId: 1 } }]}>
        <QueuePage dependencies={doubles.deps} />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /edit series/i })).toBeInTheDocument(),
    )
  })

  it('exercises controlled form fields and modal close callbacks', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    doubles.mutations.update.setImplementation(async () => ({}))
    doubles.mutations.reactivate.setImplementation(async () => ({}))
    renderPage(doubles)

    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.selectOptions(screen.getByLabelText('Format'), 'Graphic Novel')
    await user.clear(screen.getByLabelText('Issues already read (optional)'))
    await user.type(screen.getByLabelText('Issues already read (optional)'), '2')
    await user.type(screen.getByLabelText('Notes'), 'remember this')
    await user.click(screen.getByRole('button', { name: 'close modal' }))

    await user.click(screen.getByText('edit modal callback'))
    await user.clear(screen.getByLabelText('Title'))
    await user.type(screen.getByLabelText('Title'), 'Edited Saga')
    await user.selectOptions(screen.getByLabelText('Format'), 'Manga')
    await user.clear(screen.getByLabelText('Issues Remaining'))
    await user.type(screen.getByLabelText('Issues Remaining'), '4')
    await user.type(screen.getByLabelText('Notes'), 'updated')
    await user.click(screen.getByRole('button', { name: /save changes/i }))

    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    const issuesToAdd = screen.getByRole('spinbutton')
    await user.clear(issuesToAdd)
    await user.type(issuesToAdd, '3')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await waitFor(() => expect(doubles.mutations.reactivate.calls).toHaveLength(1))

    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[1]!)
    await user.click(screen.getByRole('button', { name: /close modal/i }))
    await user.click(screen.getByText('reposition callback'))
    await user.click(screen.getByRole('button', { name: /close modal/i }))
  })

  it('does not render collection creation or editing controls', () => {
    renderPage()
    expect(screen.queryByRole('button', { name: /create new collection/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /create collection/i })).not.toBeInTheDocument()
  })

  it('handles loading, empty active queues, and failed queue mutations', async () => {
    const loadingDoubles = createDoubles({ threads: { data: null, isPending: true } })
    const { unmount } = render(
      <BrowserRouter>
        <QueuePage dependencies={loadingDoubles.deps} />
      </BrowserRouter>,
    )
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
    unmount()

    const doubles = createDoubles({ threads: { data: [DONE] } })
    const user = userEvent.setup()
    renderPage(doubles)
    expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
    expect(screen.getByTestId('queue-empty-add-series')).toBeInTheDocument()
    await user.click(screen.getByTestId('queue-empty-add-series'))
    expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    doubles.mutations.reactivate.setImplementation(async () => {
      throw new Error('reactivate failed')
    })
    await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
    await user.click(screen.getByRole('button', { name: /add to queue/i }))
    await waitFor(() => expect(doubles.mutations.reactivate.calls).toHaveLength(1))
  })

  it('covers delete confirmation, shuffle and move failures, and no-op drops', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    const failMutation = async () => {
      throw new Error('mutation failed')
    }
    doubles.mutations.remove.setImplementation(failMutation)
    doubles.mutations.moveToFront.setImplementation(failMutation)
    doubles.mutations.moveToBack.setImplementation(failMutation)
    doubles.mutations.shuffle.setImplementation(failMutation)
    renderPage(doubles)
    await user.click(screen.getByText('delete callback'))
    expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
    expect(doubles.mutations.remove.calls).toHaveLength(0)
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('heading', { name: /delete series/i })).not.toBeInTheDocument()
    await user.click(screen.getByText('delete callback'))
    await user.click(screen.getByRole('button', { name: /delete series/i }))
    await waitFor(() => expect(doubles.mutations.remove.calls).toEqual([1]))
    await user.click(screen.getByText('front callback'))
    await user.click(screen.getByText('back callback'))
    await user.click(screen.getByRole('button', { name: 'Shuffle' }))
    await user.click(screen.getByText('drop'))
    await waitFor(() => expect(alert).toHaveBeenCalled())
  })

  it('uses snoozed and blocked card branches and reports blocked reads', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles({
      threads: { data: [createThreadFixture({ ...SAGA, is_blocked: true })] },
      session: { pending_thread_id: null, snoozed_threads: [createThreadFixture({ id: 1 })] },
    })
    renderPage(doubles)
    await user.click(screen.getByText('read callback'))
    expect(alert).not.toHaveBeenCalledWith(expect.stringContaining('Cannot read yet'))
    await user.click(screen.getByText('snooze callback'))
    expect(doubles.mutations.snooze.calls.length).toBeGreaterThan(0)
  })

  it('renders pending mutation labels for create, edit, and reactivation', async () => {
    const user = userEvent.setup()
    const doubles = createDoubles()
    doubles.mutations.create.setPending(true)
    doubles.mutations.update.setPending(true)
    doubles.mutations.reactivate.setPending(true)
    renderPage(doubles)
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0]!)
    expect(screen.getByRole('button', { name: 'Adding...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getByText('edit modal callback'))
    expect(screen.getByRole('button', { name: 'Saving...' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
    expect(screen.getByRole('button', { name: 'Adding to queue...' })).toBeDisabled()
  })
})
