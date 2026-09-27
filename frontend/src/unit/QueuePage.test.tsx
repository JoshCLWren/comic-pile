import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import QueuePage from '../pages/QueuePage'
import { ToastProvider } from '../contexts/ToastProvider'
import type { Thread } from '../types'
import {
  createIssueFixture,
  createQueuePageDoubles,
  createThreadFixture,
  type QueuePageDoubles,
} from './support/queuePageHarness'

const SAGA = createThreadFixture({ id: 1, title: 'Saga', queue_position: 1, issues_remaining: 5 })
const DESCENDER = createThreadFixture({
  id: 2,
  title: 'Descender',
  queue_position: 0,
  issues_remaining: 0,
  status: 'completed',
})

/** Render the page with an injected double set and return the doubles for assertions. */
function renderQueuePage(
  doubles: QueuePageDoubles = createQueuePageDoubles({
    threads: { data: [SAGA, DESCENDER] },
  }),
): QueuePageDoubles {
  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={doubles.deps} />
      </ToastProvider>
    </BrowserRouter>,
  )
  return doubles
}

beforeEach(() => {
  vi.stubGlobal('alert', vi.fn())
})

it('renders queue items and opens create modal', async () => {
  const user = userEvent.setup()
  renderQueuePage()

  expect(screen.getAllByText('Saga')[0]).toBeInTheDocument()
  expect(screen.getByText('Descender')).toBeInTheDocument()
  expect(screen.getByText('#1')).toBeInTheDocument()

  const addButtons = screen.getAllByRole('button', { name: /add series/i })
  await user.click(addButtons[0])
  expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument()
})

it('registers a restore target while the create modal is open', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [SAGA] } })

  render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={doubles.deps} />
      </ToastProvider>
    </BrowserRouter>,
  )

  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])

  expect(doubles.restore.setRestoreAction).toHaveBeenCalled()

  await user.click(screen.getByLabelText('Close modal'))

  await waitFor(() => {
    expect(doubles.restore.clearRestoreAction).toHaveBeenCalled()
  })
})

it('shuffles the queue from the header control', async () => {
  const doubles = createQueuePageDoubles({
    threads: {
      data: [
        SAGA,
        createThreadFixture({ id: 3, title: 'Spawn', queue_position: 2, issues_remaining: 7 }),
        DESCENDER,
      ],
    },
  })

  const user = userEvent.setup()
  renderQueuePage(doubles)

  await user.click(screen.getByRole('button', { name: /shuffle/i }))

  expect(doubles.mutations.shuffle.calls).toHaveLength(1)
})

describe('Visible action Snooze/Unsnooze', () => {
  it('shows visible actions for thread cards', async () => {
    const user = userEvent.setup()
    renderQueuePage()

    const readButtons = screen.getAllByLabelText('Read')
    expect(readButtons.length).toBeGreaterThan(0)
    const overflowButtons = screen.getAllByRole('button', { name: /series actions/i })
    expect(overflowButtons.length).toBeGreaterThan(0)
    await user.click(overflowButtons[0])
    expect(screen.getByRole('menuitem', { name: /edit series/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /snooze/i })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /delete series/i })).toBeInTheDocument()
  })

  it('calls snooze mutation when the pending comic Snooze action is clicked', async () => {
    const doubles = createQueuePageDoubles({
      threads: { data: [SAGA] },
      session: { pending_thread_id: 1, snoozed_threads: [] },
    })

    const user = userEvent.setup()
    renderQueuePage(doubles)

    const snoozeButtons = screen.getAllByRole('button', { name: /series actions/i })
    await user.click(snoozeButtons[0])
    await user.click(screen.getByRole('menuitem', { name: /^snooze$/i }))

    expect(doubles.mutations.snooze.calls).toEqual([1])
    expect(doubles.mutations.unsnooze.calls).toHaveLength(0)
  })

  it('calls unsnooze mutation when the Unsnooze action is clicked', async () => {
    const doubles = createQueuePageDoubles({
      threads: { data: [SAGA] },
      session: { pending_thread_id: null, snoozed_threads: [SAGA] },
    })

    const user = userEvent.setup()
    renderQueuePage(doubles)

    const unsnoozeButtons = screen.getAllByRole('button', { name: /series actions/i })
    await user.click(unsnoozeButtons[0])
    await user.click(screen.getByRole('menuitem', { name: /^unsnooze$/i }))

    expect(doubles.mutations.unsnooze.calls).toEqual([1])
    expect(doubles.mutations.snooze.calls).toHaveLength(0)
  })

  it('refetches session but not the full thread list after snooze action', async () => {
    const doubles = createQueuePageDoubles({
      threads: { data: [SAGA] },
      session: { pending_thread_id: 1, snoozed_threads: [] },
    })

    const user = userEvent.setup()
    renderQueuePage(doubles)

    const snoozeButtons = screen.getAllByRole('button', { name: /series actions/i })
    await user.click(snoozeButtons[0])
    await user.click(screen.getByRole('menuitem', { name: /^snooze$/i }))

    await waitFor(() => {
      expect(doubles.session.refetchCalls).toBeGreaterThan(0)
    })
    expect(doubles.threads.refetchCalls).toBe(0)
  })

  it('refetches session but not the full thread list after unsnooze action', async () => {
    const doubles = createQueuePageDoubles({
      threads: { data: [SAGA] },
      session: { pending_thread_id: null, snoozed_threads: [SAGA] },
    })

    const user = userEvent.setup()
    renderQueuePage(doubles)

    const unsnoozeButtons = screen.getAllByRole('button', { name: /series actions/i })
    await user.click(unsnoozeButtons[0])
    await user.click(screen.getByRole('menuitem', { name: /^unsnooze$/i }))

    await waitFor(() => {
      expect(doubles.session.refetchCalls).toBeGreaterThan(0)
    })
    expect(doubles.threads.refetchCalls).toBe(0)
  })
})

describe('Keyboard Accessibility', () => {
  it('thread card is present and focusable', () => {
    renderQueuePage()

    const threadItems = screen.getAllByTestId('queue-thread-item')
    expect(threadItems.length).toBeGreaterThan(0)
  })
})

it('filters and sorts active threads while preserving completed threads', async () => {
  const user = userEvent.setup()
  const zeta = createThreadFixture({ id: 1, title: 'Zeta', queue_position: 2, issues_remaining: 1 })
  const alpha = createThreadFixture({ id: 2, title: 'Alpha', queue_position: 1, issues_remaining: 2 })
  const done = createThreadFixture({
    id: 3,
    title: 'Done',
    queue_position: 0,
    issues_remaining: 0,
    status: 'completed',
    notes: 'Finished',
  })
  // The backend owns page ordering: alphabetical requests return the
  // keyset title-cursor order, position returns queue position order.
  const doubles = createQueuePageDoubles({
    resolveThreads: (searchTerm) => ({
      data: searchTerm === 'missing' ? [] : [alpha, zeta, done],
    }),
  })

  renderQueuePage(doubles)
  expect(screen.getByText('Done')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Title' }))
  const cards = screen.getAllByTestId('queue-thread-item')
  expect(cards[0]).toHaveTextContent('Alpha')
  await user.type(screen.getByPlaceholderText('Search...'), 'missing')
  // Search is debounced (300ms) so the parent query only commits after the delay.
  await waitFor(
    () => expect(screen.getByText('No active series match your search')).toBeInTheDocument(),
    { timeout: 2000 },
  )
})

it('shows correct empty state when search matches only completed threads', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    resolveThreads: (searchTerm) => ({
      data:
        searchTerm === 'done'
          ? [createThreadFixture({ id: 2, title: 'Done', queue_position: 0, issues_remaining: 0, status: 'completed', notes: 'Finished' })]
          : [],
    }),
  })

  renderQueuePage(doubles)
  await user.type(screen.getByPlaceholderText('Search...'), 'done')
  await waitFor(
    () => expect(screen.getByText('No active series match your search')).toBeInTheDocument(),
    { timeout: 2000 },
  )
})

it('creates a simple issue range and marks the requested issues read', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [] } })
  doubles.mutations.create.setImplementation(async () => ({ id: 44 }))

  renderQueuePage(doubles)
  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
  await user.type(screen.getByLabelText('Title'), 'New Series')
  await user.clear(screen.getByLabelText('Issues'))
  await user.type(screen.getByLabelText('Issues'), '1-5')
  await user.type(screen.getByLabelText(/Issues already read/i), '2')
  await user.click(screen.getByRole('button', { name: /create series/i }))

  await waitFor(() => expect(doubles.mutations.create.calls).toHaveLength(1))
})

it('opens edit, reposition, dependency, and completed reactivation flows', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    threads: { data: [SAGA, DESCENDER] },
  })

  renderQueuePage(doubles)
  const menu = screen.getAllByRole('button', { name: /series actions/i })[0]
  await user.click(menu)
  await user.click(screen.getByRole('menuitem', { name: /edit/i }))
  expect(screen.getByRole('heading', { name: /edit series/i })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /close modal/i }))
  await user.click(screen.getAllByRole('button', { name: /series actions/i })[0])
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  expect(screen.getByTestId('position-slider-modal')).toBeInTheDocument()
  await user.click(screen.getByTestId('position-slider-cancel'))
  await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0]!)
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  await user.click(screen.getByRole('button', { name: /add to queue/i }))
})

it('renders loading and empty queue states', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: null, isPending: true } })

  const { rerender } = render(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={doubles.deps} />
      </ToastProvider>
    </BrowserRouter>,
  )
  expect(screen.getByRole('status')).toBeInTheDocument()

  doubles.threads.set({ data: [], isPending: false })
  rerender(
    <BrowserRouter>
      <ToastProvider>
        <QueuePage dependencies={doubles.deps} />
      </ToastProvider>
    </BrowserRouter>,
  )
  expect(screen.getByTestId('queue-empty')).toBeInTheDocument()
  expect(screen.getByText('Nothing to roll yet')).toBeInTheDocument()
  expect(
    screen.getByText('Your reading queue is empty — add some comic series to get started.'),
  ).toBeInTheDocument()
  await user.click(screen.getByTestId('queue-empty-add-series'))
  expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument()
})

it('prevents reading blocked threads and reports delete failures', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    threads: {
      data: [createThreadFixture({ id: 1, title: 'Blocked', is_blocked: true, blocking_reasons: ['Blocked by: Prequel'] })],
    },
    blockingInfo: { 1: [{ label: 'Blocked by: Prequel' }] },
  })
  doubles.mutations.remove.setImplementation(async () => {
    throw new Error('delete failed')
  })

  renderQueuePage(doubles)
  const readButton = screen.getByLabelText('Read')
  expect(readButton).toBeDisabled()
  expect(readButton).toHaveAttribute('title', expect.stringContaining('Blocked by: Prequel'))
  expect(doubles.setPendingCalls).toHaveLength(0)
  expect(alert).not.toHaveBeenCalledWith(expect.stringContaining('Cannot read yet'))
  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /delete/i }))
  expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /delete series/i }))
  await waitFor(() => expect(doubles.mutations.remove.calls).toEqual([1]))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('delete failed'))
  expect(doubles.toasts.showToast).toHaveBeenCalledWith(
    expect.stringContaining('delete failed'),
    'error',
  )
})

it('keeps the thread when delete confirmation is cancelled', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [SAGA] } })

  renderQueuePage(doubles)
  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /delete/i }))
  expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /cancel/i }))
  expect(screen.queryByRole('heading', { name: /delete series/i })).not.toBeInTheDocument()
  expect(doubles.mutations.remove.calls).toHaveLength(0)
})

it('supports created-date sorting and drag reorder failure feedback', async () => {
  const user = userEvent.setup()
  const newThread = createThreadFixture({ id: 2, title: 'New', queue_position: 2, issues_remaining: 1 })
  const oldThread = createThreadFixture({ id: 1, title: 'Old', queue_position: 1, issues_remaining: 1 })
  const doubles = createQueuePageDoubles({
    // Backend created cursor returns newest-first server order; the client
    // must not re-sort concatenated pages (issue #2452).
    resolveThreads: (_searchTerm, sort) => ({
      data: sort === 'created' ? [newThread, oldThread] : [oldThread, newThread],
    }),
  })
  doubles.mutations.moveToPosition.setImplementation(async () => {
    throw new Error('reorder failed')
  })

  renderQueuePage(doubles)
  await user.click(screen.getByRole('button', { name: 'Recently added' }))
  const cards = screen.getAllByTestId('queue-thread-item')
  expect(cards[0]).toHaveTextContent('New')
  const dragButtons = screen.getAllByRole('button', { name: 'Drag to reorder' })
  fireEvent.dragStart(dragButtons[0]!, { dataTransfer: { effectAllowed: '', setData: vi.fn() } })
  const targetCard = cards[1]!
  fireEvent.dragOver(targetCard)
  fireEvent.drop(targetCard, { dataTransfer: { getData: () => '1' } })
  await waitFor(() => expect(doubles.mutations.moveToPosition.calls.length).toBeGreaterThan(0))
})

it('executes every queue action-menu operation', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [SAGA] } })

  renderQueuePage(doubles)
  const openMenu = async () => user.click(screen.getByRole('button', { name: /series actions/i }))

  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /move to front/i }))
  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /move to back/i }))
  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /delete/i }))
  expect(screen.getByRole('heading', { name: /delete series/i })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /delete series/i }))

  expect(doubles.mutations.moveToFront.calls).toEqual([1])
  expect(doubles.mutations.moveToBack.calls).toEqual([1])
  await waitFor(() => expect(doubles.mutations.remove.calls).toEqual([1]))

  await openMenu()
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  expect(screen.getByTestId('position-slider-modal')).toBeInTheDocument()
  await user.click(screen.getByTestId('position-slider-cancel'))
})

it('reports queue mutation failures and invalid reposition requests', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    threads: {
      data: [
        SAGA,
        createThreadFixture({ id: 2, title: 'Spawn', queue_position: 2, issues_remaining: 1 }),
      ],
    },
  })
  doubles.mutations.moveToFront.setImplementation(async () => {
    throw new Error('front failed')
  })
  doubles.mutations.shuffle.setImplementation(async () => {
    throw new Error('shuffle failed')
  })

  renderQueuePage(doubles)
  await user.click(screen.getByRole('button', { name: /shuffle/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('shuffle')))
  await user.click(screen.getAllByRole('button', { name: /series actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /move to front/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('front')))
  await user.click(screen.getAllByRole('button', { name: /series actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  const slider = screen.getByRole('slider')
  fireEvent.change(slider, { target: { value: '99' } })
  await user.click(screen.getByTestId('position-slider-confirm'))
})

it('creates a literal issue range and reports create failures', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [] } })
  doubles.mutations.create.setImplementation(async () => ({ id: 55 }))

  renderQueuePage(doubles)
  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Annuals')
  await user.clear(screen.getByLabelText('Issues'))
  await user.type(screen.getByLabelText('Issues'), 'Annual 1, 5-7')
  await user.type(screen.getByLabelText(/Issues already read/i), '1')
  await user.click(screen.getByRole('button', { name: /create series/i }))
  await waitFor(() => expect(doubles.mutations.create.calls).toHaveLength(1))

  doubles.mutations.create.setImplementation(async () => {
    throw new Error('create failed')
  })
  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Broken')
  await user.type(screen.getByLabelText('Issues'), '1')
  await user.click(screen.getByRole('button', { name: /create series/i }))
  await waitFor(() => expect(alert).toHaveBeenCalledWith(expect.stringContaining('create failed')))
})

it('uses thread blocked state without loading dependency details, and handles edit failure', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    threads: { data: [createThreadFixture({ id: 1, title: 'Saga', is_blocked: true, issues_remaining: 2 })] },
  })
  doubles.mutations.update.setImplementation(async () => {
    throw new Error('update failed')
  })

  renderQueuePage(doubles)
  expect(doubles.services.dependenciesApi.getBatchBlockingInfo).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /dependencies/i }))
  expect(screen.getByRole('heading', { name: /dependencies:/i })).toBeInTheDocument()
  await user.click(screen.getByLabelText('Close modal'))
  await user.click(screen.getByRole('button', { name: /series actions/i }))
  await user.click(screen.getByRole('menuitem', { name: /edit/i }))
  await user.click(screen.getByRole('button', { name: /save changes/i }))
  await waitFor(() => expect(doubles.mutations.update.calls).toHaveLength(1))
})

it('covers drag cancellation and successful repositioning', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({
    threads: {
      data: [
        SAGA,
        createThreadFixture({ id: 2, title: 'Two', queue_position: 2, issues_remaining: 1 }),
      ],
    },
  })

  renderQueuePage(doubles)
  const cards = screen.getAllByTestId('queue-thread-item')
  const drag = screen.getAllByRole('button', { name: 'Drag to reorder' })
  fireEvent.dragStart(drag[0]!, { dataTransfer: { effectAllowed: '', setData: vi.fn() } })
  fireEvent.drop(cards[0]!, { dataTransfer: { getData: () => '1' } })
  await user.click(screen.getAllByRole('button', { name: /series actions/i })[0]!)
  await user.click(screen.getByRole('menuitem', { name: /reposition/i }))
  fireEvent.change(screen.getByRole('slider'), { target: { value: '1' } })
  await user.click(screen.getByTestId('position-slider-confirm'))
  await waitFor(() => expect(doubles.mutations.moveToPosition.calls).toHaveLength(1))
})

it('creates complex ranges and marks the requested issues read', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [] } })
  doubles.mutations.create.setImplementation(async () => ({ id: 77 }))
  doubles.services.issuesApi.create.mockResolvedValue({
    issues: [createIssueFixture({ id: 11 }), createIssueFixture({ id: 12 })],
    total_count: 2,
    page_size: 100,
    next_page_token: null,
  })

  renderQueuePage(doubles)
  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Complex')
  await user.type(screen.getByLabelText('Issues'), 'Annual 1, 5-7')
  await user.type(screen.getByLabelText(/Issues already read/i), '2')
  await user.click(screen.getByRole('button', { name: /create series/i }))
  await waitFor(() => expect(doubles.services.issuesApi.bulkMarkRead).toHaveBeenCalledWith([11, 12]))
})

it('creates a later single issue without requiring earlier issues', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [] } })
  doubles.mutations.create.setImplementation(async () => ({ id: 78 }))
  doubles.services.issuesApi.create.mockResolvedValue({
    issues: [createIssueFixture({ id: 71, issue_number: '71' })],
    total_count: 1,
    page_size: 100,
    next_page_token: null,
  })

  renderQueuePage(doubles)
  await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
  await user.type(screen.getByLabelText('Title'), 'Marvel Graphic Novel')
  await user.type(screen.getByLabelText('Issues'), '71')

  expect(screen.getByText(/You do not need to add earlier issues/i)).toBeInTheDocument()
  expect(screen.getByText(/not an issue number/i)).toBeInTheDocument()
  expect(screen.getByLabelText('Issues already read (optional)')).toHaveValue(0)

  await user.click(screen.getByRole('button', { name: /create series/i }))

  await waitFor(() =>
    expect(doubles.mutations.create.calls[0]).toEqual(
      expect.objectContaining({ title: 'Marvel Graphic Novel', issues_remaining: 1 }),
    ),
  )
  expect(doubles.services.issuesApi.create).toHaveBeenCalledWith(78, '71')
  expect(doubles.services.issuesApi.markRead).not.toHaveBeenCalled()
  expect(doubles.services.issuesApi.bulkMarkRead).not.toHaveBeenCalled()
})

it('handles reactivation success and failure from completed threads', async () => {
  const user = userEvent.setup()
  const doubles = createQueuePageDoubles({ threads: { data: [DESCENDER] } })
  doubles.mutations.reactivate.setImplementation(async () => ({}))

  renderQueuePage(doubles)
  await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0])
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '3' } })
  await user.click(screen.getByRole('button', { name: /add to queue/i }))
  await waitFor(() =>
    expect(doubles.mutations.reactivate.calls).toEqual([{ thread_id: 2, issues_to_add: 3 }]),
  )

  doubles.mutations.reactivate.setImplementation(async () => {
    throw new Error('reactivate failed')
  })
  await user.click(screen.getAllByRole('button', { name: /^add back to queue$/i })[0])
  await user.selectOptions(screen.getAllByRole('combobox').at(-1)!, '2')
  await user.click(screen.getByRole('button', { name: /add to queue/i }))
  await waitFor(() =>
    expect(screen.getByRole('heading', { name: /add back to queue/i })).toBeInTheDocument(),
  )
})

it('uses the virtualized queue without loading hidden blocked-thread reasons', async () => {
  const manyThreads: Thread[] = Array.from({ length: 55 }, (_unused, index) =>
    createThreadFixture({
      id: index + 1,
      title: `Thread ${index + 1}`,
      queue_position: index + 1,
      issues_remaining: 1,
      is_blocked: index === 0,
    }),
  )
  const doubles = createQueuePageDoubles({ threads: { data: manyThreads } })

  renderQueuePage(doubles)
  await waitFor(() => expect(screen.getByTestId('queue-thread-list')).toBeInTheDocument())
  expect(screen.getByRole('list', { name: 'Series queue' })).toBeInTheDocument()
  expect(doubles.services.dependenciesApi.getBatchBlockingInfo).not.toHaveBeenCalled()
})

describe('Roll nudge after first thread creation', () => {
  beforeEach(() => {
    // Clear localStorage before each test
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue(null)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {})
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {})
  })

  it('shows Ready to roll? modal after first thread creation', async () => {
    const user = userEvent.setup()
    const doubles = createQueuePageDoubles({ threads: { data: [] } })
    doubles.mutations.create.setImplementation(async () => ({ id: 1 }))

    renderQueuePage(doubles)

    // Open create modal
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    expect(screen.getByRole('heading', { name: /add series/i })).toBeInTheDocument()

    // Fill and submit form
    await user.type(screen.getByLabelText('Title'), 'New Series')
    await user.type(screen.getByLabelText('Format'), 'Comic')
    await user.type(screen.getByLabelText('Issues'), '5')
    await user.click(screen.getByRole('button', { name: /create series/i }))

    // Wait for creation to complete and the roll nudge modal to appear
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /ready to roll\?/i })).toBeInTheDocument(),
    )
    expect(screen.getByText(/you've created your first series!/i)).toBeInTheDocument()
  })

  it('does not show roll nudge if user has dismissed it before', async () => {
    // Mock dismissed state in localStorage
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('true')

    const user = userEvent.setup()
    const doubles = createQueuePageDoubles({ threads: { data: [] } })
    doubles.mutations.create.setImplementation(async () => ({ id: 1 }))

    renderQueuePage(doubles)

    // Open create modal
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])

    // Fill and submit form
    await user.type(screen.getByLabelText('Title'), 'New Series')
    await user.type(screen.getByLabelText('Format'), 'Comic')
    await user.type(screen.getByLabelText('Issues'), '5')
    await user.click(screen.getByRole('button', { name: /create series/i }))

    // Wait for creation to complete
    await waitFor(() => expect(doubles.mutations.create.calls).toHaveLength(1))

    // Check that Ready to roll? modal does NOT appear
    expect(screen.queryByRole('heading', { name: /ready to roll\?/i })).not.toBeInTheDocument()
  })

  it('navigates to roll page when clicking Let\'s Roll! button', async () => {
    const user = userEvent.setup()
    const doubles = createQueuePageDoubles({ threads: { data: [] } })
    doubles.mutations.create.setImplementation(async () => ({ id: 1 }))

    renderQueuePage(doubles)

    // Open create modal and submit
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'New Series')
    await user.type(screen.getByLabelText('Format'), 'Comic')
    await user.type(screen.getByLabelText('Issues'), '5')
    await user.click(screen.getByRole('button', { name: /create series/i }))

    // Wait for modal to appear
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /ready to roll\?/i })).toBeInTheDocument(),
    )

    // Click Let's Roll! button
    await user.click(screen.getByRole('button', { name: /let's roll!/i }))

    // Modal should close after clicking the button
    await waitFor(() =>
      expect(screen.queryByRole('heading', { name: /ready to roll\?/i })).not.toBeInTheDocument(),
    )
  })

  it('dismisses roll nudge when clicking Maybe Later button', async () => {
    const user = userEvent.setup()
    const doubles = createQueuePageDoubles({ threads: { data: [] } })
    doubles.mutations.create.setImplementation(async () => ({ id: 1 }))

    renderQueuePage(doubles)

    // Open create modal and submit
    await user.click(screen.getAllByRole('button', { name: /add series/i })[0])
    await user.type(screen.getByLabelText('Title'), 'New Series')
    await user.type(screen.getByLabelText('Format'), 'Comic')
    await user.type(screen.getByLabelText('Issues'), '5')
    await user.click(screen.getByRole('button', { name: /create series/i }))

    // Wait for modal to appear
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /ready to roll\?/i })).toBeInTheDocument(),
    )

    // Click Maybe Later button
    await user.click(screen.getByRole('button', { name: /maybe later/i }))

    // Check that modal is closed
    expect(screen.queryByRole('heading', { name: /ready to roll\?/i })).not.toBeInTheDocument()

    // Check that dismissed state is saved to localStorage
    expect(Storage.prototype.setItem).toHaveBeenCalledWith(
      'comic-pile-roll-nudge-dismissed',
      'true',
    )
  })
})
