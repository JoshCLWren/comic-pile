import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ContainerQueueActions from '../components/ContainerQueueActions'

const mocks = vi.hoisted(() => ({
  checkExcludedStatus: vi.fn(),
  bulkExclude: vi.fn(),
  bulkRestore: vi.fn(),
  checkThreadMemberships: vi.fn(),
  useCrossoverGroups: vi.fn(),
  invalidateAfterQueueMutation: vi.fn(),
  invalidateCrossoverGroupsForThreads: vi.fn(),
}))

vi.mock('../services/api-threads', () => ({
  threadsApi: {
    checkExcludedStatus: mocks.checkExcludedStatus,
    bulkExclude: mocks.bulkExclude,
    bulkRestore: mocks.bulkRestore,
  },
}))

vi.mock('../services/api-custom-cbl', () => ({
  customCBLApi: {
    checkThreadMemberships: mocks.checkThreadMemberships,
  },
}))

vi.mock('../hooks/useCrossoverGroups', () => ({
  useCrossoverGroups: (ids: number[]) => mocks.useCrossoverGroups(ids),
}))

vi.mock('../query/cacheEffects', () => ({
  invalidateAfterQueueMutation: (...args: unknown[]) => mocks.invalidateAfterQueueMutation(...args),
  invalidateCrossoverGroupsForThreads: (...args: unknown[]) =>
    mocks.invalidateCrossoverGroupsForThreads(...args),
}))

function renderActions(props?: Partial<Parameters<typeof ContainerQueueActions>[0]>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ContainerQueueActions
        sourceKind="reading_list"
        sourceId={7}
        sourceName="Test List"
        memberThreads={[
          { id: 1, title: 'Alpha' },
          { id: 2, title: 'Beta' },
          { id: 3, title: 'Gamma' },
        ]}
        {...props}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.checkExcludedStatus.mockResolvedValue({ excluded_thread_ids: [0, 3], active_thread_ids: [1, 2] })
  mocks.checkThreadMemberships.mockResolvedValue({ thread_ids: [2] })
  mocks.useCrossoverGroups.mockReturnValue({ groupsByThreadId: {}, isPending: false, error: null })
  mocks.bulkExclude.mockResolvedValue({ group: { id: 11 }, excluded_thread_ids: [1] })
  mocks.bulkRestore.mockResolvedValue({ restored_thread_ids: [3] })
  mocks.invalidateAfterQueueMutation.mockResolvedValue(undefined)
  mocks.invalidateCrossoverGroupsForThreads.mockResolvedValue(undefined)
})

describe('ContainerQueueActions', () => {
  it('renders nothing when there are no member threads', () => {
    const { container } = renderActions({ memberThreads: [] })
    expect(container).toBeEmptyDOMElement()
  })

  it('checks membership in bounded batches for large containers', async () => {
    const memberThreads = Array.from({ length: 4501 }, (_, index) => ({
      id: index + 1,
      title: `Series ${index + 1}`,
    }))
    mocks.checkExcludedStatus.mockResolvedValue({
      excluded_thread_ids: [],
      active_thread_ids: memberThreads.map((thread) => thread.id),
    })
    mocks.checkThreadMemberships.mockResolvedValue({ thread_ids: [] })

    const user = userEvent.setup()
    renderActions({ memberThreads })

    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))

    await waitFor(() => expect(mocks.checkThreadMemberships).toHaveBeenCalled())
    expect(mocks.checkThreadMemberships.mock.calls.length).toBeGreaterThan(4)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove from Queue' })).toBeEnabled(),
    )
  })

  it('removes selected series after overlap checks complete', async () => {
    let resolveMemberships!: (value: { thread_ids: number[] }) => void
    mocks.checkThreadMemberships.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMemberships = resolve
        }),
    )

    const user = userEvent.setup()
    renderActions()

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalledWith([1, 2, 3]))
    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))

    expect(await screen.findByText(/Checking for series in other active lists/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove from Queue' })).toBeDisabled()
    resolveMemberships({ thread_ids: [2] })
    await waitFor(() =>
      expect(screen.queryByText(/Checking for series in other active lists/)).not.toBeInTheDocument(),
    )

    // Beta (id 2) is in another list and should be keepable; keep it.
    const keep = await screen.findByLabelText('Keep in Queue')
    await user.click(keep)
    await user.click(screen.getByRole('button', { name: 'Remove from Queue' }))

    await waitFor(() => {
      expect(mocks.bulkExclude).toHaveBeenCalledWith({
        thread_ids: [1],
        source: { kind: 'reading_list', id: 7, name: 'Test List' },
      })
    })
  })

  it('blocks removal when overlap checks fail and allows retry', async () => {
    let resolveManualRetry!: (value: { thread_ids: number[] }) => void
    mocks.checkThreadMemberships
      .mockRejectedValueOnce(new Error('boom'))
      .mockRejectedValueOnce(new Error('boom'))
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveManualRetry = resolve
          }),
      )

    const user = userEvent.setup()
    renderActions()

    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))
    await waitFor(() => expect(mocks.checkThreadMemberships).toHaveBeenCalledTimes(2))
    expect(
      await screen.findByText(/Could not check whether these series belong to other active lists/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove from Queue' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(mocks.checkThreadMemberships).toHaveBeenCalledTimes(3))
    resolveManualRetry({ thread_ids: [] })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove from Queue' })).not.toBeDisabled(),
    )
  })

  it('restores excluded members from the container', async () => {
    const user = userEvent.setup()
    renderActions()

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalledWith([1, 2, 3]))
    await user.click(await screen.findByRole('button', { name: 'Restore all to Queue' }))
    await user.click(screen.getByRole('button', { name: 'Restore to Queue' }))

    await waitFor(() => {
      expect(mocks.bulkRestore).toHaveBeenCalledWith([3])
    })
  })

  it('shows member-status error and retries excluded lookup', async () => {
    mocks.checkExcludedStatus.mockRejectedValueOnce(new Error('nope'))
    mocks.checkExcludedStatus.mockResolvedValueOnce({ excluded_thread_ids: [3], active_thread_ids: [1, 2] })
    const user = userEvent.setup()
    renderActions()

    expect(await screen.findByText(/Could not determine which series are currently in the Queue/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.queryByText(/Could not determine which series are currently in the Queue/)).not.toBeInTheDocument())
  })

  it('handles remove and restore mutation failures and cancel actions', async () => {
    mocks.bulkExclude.mockRejectedValueOnce(new Error('remove failed'))
    mocks.bulkRestore.mockRejectedValueOnce(new Error('restore failed'))
    const user = userEvent.setup()
    renderActions()

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalled())
    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))
    const removeConfirm = await screen.findByRole('button', { name: 'Remove from Queue' })
    await waitFor(() => expect(removeConfirm).not.toBeDisabled())
    await user.click(removeConfirm)
    expect(await screen.findByText('remove failed')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Remove all series from Queue' })).not.toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Restore all to Queue' }))
    const restoreConfirm = await screen.findByRole('button', { name: 'Restore to Queue' })
    await user.click(restoreConfirm)
    expect(await screen.findByText('restore failed')).toBeInTheDocument()
  })

  it('shows empty remove/restore states when all members are already in the opposite state', async () => {
    mocks.checkExcludedStatus.mockResolvedValue({ excluded_thread_ids: [1, 2] })
    const user = userEvent.setup()
    renderActions({ memberThreads: [{ id: 1, title: 'Alpha' }, { id: 2, title: 'Beta' }] })

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalledWith([1, 2]))
    expect(await screen.findByRole('button', { name: 'Remove all series from Queue' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Restore all to Queue' }))
    expect(await screen.findByText(/Restore every excluded series from this collection/)).toBeInTheDocument()
  })

  it('supports reading plan sources and crossover overlap keep toggles', async () => {
    mocks.checkExcludedStatus.mockResolvedValue({ excluded_thread_ids: [], active_thread_ids: [1, 2, 3] })
    mocks.checkThreadMemberships.mockResolvedValue({ thread_ids: [] })
    mocks.useCrossoverGroups.mockReturnValue({
      groupsByThreadId: { 2: [{ id: 99, name: 'Other' }] },
      isPending: false,
      error: null,
    })
    const user = userEvent.setup()
    renderActions({ sourceKind: 'reading_plan', sourceId: 5, sourceName: 'Plan X' })

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalled())
    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))
    const removeConfirm = await screen.findByRole('button', { name: 'Remove from Queue' })
    await waitFor(() => expect(removeConfirm).not.toBeDisabled())
    expect(mocks.checkThreadMemberships).toHaveBeenCalledWith([1, 2, 3], undefined)
    const keep = await screen.findByLabelText('Keep in Queue')
    await user.click(keep)
    await user.click(keep)
    await user.click(removeConfirm)
    await waitFor(() => {
      expect(mocks.bulkExclude).toHaveBeenCalledWith({
        thread_ids: [1, 2, 3],
        source: { kind: 'reading_plan', id: 5, name: 'Plan X' },
      })
    })
  })

  it('does not treat the current crossover group as an external overlap', async () => {
    mocks.checkExcludedStatus.mockResolvedValue({ excluded_thread_ids: [], active_thread_ids: [1, 2, 3] })
    mocks.checkThreadMemberships.mockResolvedValue({ thread_ids: [] })
    mocks.useCrossoverGroups.mockReturnValue({
      groupsByThreadId: { 1: [{ id: 7, name: 'Same crossover' }] },
      isPending: false,
      error: null,
    })
    const user = userEvent.setup()
    renderActions({ sourceKind: 'crossover', sourceId: 7, sourceName: 'Same crossover' })

    await waitFor(() => expect(mocks.checkExcludedStatus).toHaveBeenCalled())
    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))
    const removeConfirm = await screen.findByRole('button', { name: 'Remove from Queue' })
    await waitFor(() => expect(removeConfirm).not.toBeDisabled())
    expect(screen.queryByLabelText('Keep in Queue')).not.toBeInTheDocument()
    await user.click(removeConfirm)
    await waitFor(() => {
      expect(mocks.bulkExclude).toHaveBeenCalledWith({
        thread_ids: [1, 2, 3],
        source: { kind: 'crossover', id: 7, name: 'Same crossover' },
      })
    })
  })

  it('does not offer completed non-excluded series for removal', async () => {
    mocks.checkExcludedStatus.mockResolvedValue({ excluded_thread_ids: [], active_thread_ids: [1] })
    mocks.checkThreadMemberships.mockResolvedValue({ thread_ids: [] })
    const user = userEvent.setup()
    renderActions()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove all series from Queue' })).toBeEnabled(),
    )
    await user.click(screen.getByRole('button', { name: 'Remove all series from Queue' }))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Remove from Queue' })).toBeEnabled(),
    )
    expect(screen.getByText('1 of 1 series will be removed.')).toBeInTheDocument()
    expect(screen.queryByText('Beta')).not.toBeInTheDocument()
    expect(screen.queryByText('Gamma')).not.toBeInTheDocument()
  })

  it('disables queue actions while member status is loading', () => {
    mocks.checkExcludedStatus.mockReturnValue(new Promise(() => {}))
    renderActions()
    expect(screen.getByRole('button', { name: 'Remove all series from Queue' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Restore all to Queue' })).toBeDisabled()
  })

  it('closes the remove modal with the dialog close control', async () => {
    const user = userEvent.setup()
    renderActions()

    await user.click(await screen.findByRole('button', { name: 'Remove all series from Queue' }))
    await screen.findByRole('button', { name: 'Remove from Queue' })
    await user.click(screen.getByRole('button', { name: 'Close modal' }))

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Remove from Queue' })).not.toBeInTheDocument(),
    )
  })

  it('closes the restore modal with cancel and the dialog close control', async () => {
    const user = userEvent.setup()
    renderActions()

    await user.click(await screen.findByRole('button', { name: 'Restore all to Queue' }))
    await screen.findByRole('button', { name: 'Restore to Queue' })
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Restore to Queue' })).not.toBeInTheDocument(),
    )

    await user.click(screen.getByRole('button', { name: 'Restore all to Queue' }))
    await screen.findByRole('button', { name: 'Restore to Queue' })
    await user.click(screen.getByRole('button', { name: 'Close modal' }))
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: 'Restore to Queue' })).not.toBeInTheDocument(),
    )
  })
})
