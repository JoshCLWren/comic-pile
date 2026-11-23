import { fireEvent, render, screen, waitFor } from './testingLibrary'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { ToastProvider } from '../contexts/ToastProvider'
import { injectModuleDoubles } from './injectModuleDoubles'
import { MemoryRouter } from 'react-router-dom'
import { NavigationSpy } from './routerTestHarness'

// SAFETY: Hoisted bootstrap modal state holds nullable manualDie; null represents automatic die mode in the fixture.
const state = vi.hoisted(() => ({ overridePending: false, setDiePending: false, manualDie: null as number | null }))
const spies = vi.hoisted(() => ({
  list: vi.fn(), override: vi.fn(), refetch: vi.fn(), navigate: vi.fn(), setDie: vi.fn(), clearDie: vi.fn(),
}))

await injectModuleDoubles(await import('../contexts/useBugReportRestore'), () => ({
  useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }),
}))
await injectModuleDoubles(await import('../hooks/useRollBootstrap'), () => ({
  useRollBootstrap: () => ({
    data: {
      current_die: 6,
      manual_die: state.manualDie,
      last_rolled_result: null,
      pending_thread_id: null,
      active_thread: null,
      roll_pool: [{ id: 1, title: 'Saga', format: 'Comic' }],
      snoozed_threads: [{ id: 2, title: 'Watchmen', format: 'Comic' }],
      snoozed_count: 1,
      skipped_thread_ids: [],
      skipped_threads: [],
    },
    refetch: spies.refetch,
    isPending: false,
    isError: false,
    error: null,
  }),
}))
await injectModuleDoubles(await import('../hooks/useRoll'), () => ({
  useUnsnooze: () => ({ mutate: vi.fn().mockResolvedValue({}), isPending: false }),
  useSetDie: () => ({ mutate: spies.setDie, isPending: state.setDiePending }),
  useResetDice: () => ({ mutate: vi.fn().mockResolvedValue({ die: 6, replayed: false }), isPending: false }),
  useRoll: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissPending: () => ({ mutate: vi.fn(), isPending: false }),
  useOverrideRoll: () => ({ mutate: spies.override, isPending: state.overridePending }),
}))
await injectModuleDoubles(await import('../hooks/useSnooze'), () => ({
  useSnooze: () => ({ mutate: vi.fn(), isPending: false }),
  useUnsnooze: () => ({ mutate: vi.fn(), isPending: false }),
}))
await injectModuleDoubles(await import('../hooks/useQueue'), () => ({
  useMoveToFront: () => ({ mutate: vi.fn(), isPending: false }),
  useMoveToBack: () => ({ mutate: vi.fn(), isPending: false }),
  useShuffleQueue: () => ({ mutate: vi.fn(), isPending: false }),
  useActiveSeriesCount: () => null,
  useRestoreExclusionGroup: () => ({ mutate: vi.fn(), isPending: false, isError: false }),
}))
await injectModuleDoubles(await import('../hooks'), () => ({ useRate: () => ({ mutate: vi.fn(), isPending: false }) }))
await injectModuleDoubles(await import('../services/api-taste'), () => ({
  tasteApi: {
    getDiscoveries: vi.fn().mockResolvedValue({ discoveries: [], generated_at: new Date().toISOString() }),
    dismiss: vi.fn().mockResolvedValue({ dismissed: true }),
    submitVerdict: vi.fn().mockResolvedValue({}),
  },
}))
await injectModuleDoubles(await import('../services/api-threads'), () => ({ threadsApi: { list: spies.list, setPending: vi.fn() } }))
await injectModuleDoubles(await import('../services/api'), () => ({
  threadsApi: {
    list: spies.list,
    setPending: vi.fn(),
  },
  dependenciesApi: {
    getConnectedThreads: vi.fn().mockResolvedValue({ connected_threads: [] }),
    getBlockingInfo: vi.fn().mockResolvedValue({ blocking_reasons: [] }),
  },
}))
await injectModuleDoubles(await import('../services/api-reading-orders'), () => ({
  readingOrdersApi: { getForThread: vi.fn().mockResolvedValue({ reading_orders: [] }) },
}))
await injectModuleDoubles(await import('../components/LazyDice3D'), () => ({
  default: ({ onRollComplete }: { onRollComplete?: () => void }) => (
    <button type="button" onClick={onRollComplete}>complete dice</button>
  ),
}))
await injectModuleDoubles(await import('../components/Tooltip'), () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
await injectModuleDoubles(await import('../components/GlossaryLink'), () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
await injectModuleDoubles(await import('../components/Modal'), () => ({
  default: ({ isOpen, title, children, onClose }: { isOpen: boolean; title: string; children: React.ReactNode; onClose: () => void }) =>
    isOpen ? <section><h2>{title}</h2><button type="button" onClick={onClose}>close modal</button>{children}</section> : null,
}))
<<<<<<< HEAD
await injectModuleDoubles(await import('../components/MigrationDialog'), () => ({ default: () => null }))
await injectModuleDoubles(await import('../components/SimpleMigrationDialog'), () => ({ default: () => null }))
await injectModuleDoubles(await import('../pages/RollPage/components/ThreadPool'), () => ({ ThreadPool: () => <div>pool</div> }))
await injectModuleDoubles(await import('../pages/RollPage/components/RatingView'), () => ({ RatingView: () => <div>rating</div> }))

function renderRollPage() {
  return render(
    <MemoryRouter>
      <NavigationSpy navigate={spies.navigate} />
      <ToastProvider>
        <RollPage />
      </ToastProvider>
    </MemoryRouter>,
  )
}
=======
vi.mock('../components/DirectReadIssuePanel', () => ({
  DirectReadIssuePanel: ({ threadTitle }: { threadTitle: string }) => <div>Direct issue card for {threadTitle}</div>,
}))
vi.mock('../components/MigrationDialog', () => ({ default: () => null }))
vi.mock('../components/SimpleMigrationDialog', () => ({ default: () => null }))
vi.mock('../pages/RollPage/components/ThreadPool', () => ({ ThreadPool: () => <div>pool</div> }))
vi.mock('../pages/RollPage/components/RatingView', () => ({ RatingView: () => <div>rating</div> }))
>>>>>>> origin/main

describe('RollPage bootstrap modal coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    state.overridePending = false
    state.setDiePending = false
    state.manualDie = null
    spies.list.mockResolvedValue({
      threads: [{ id: 1, title: 'Saga', format: 'Comic', status: 'active' }],
      next_page_token: null,
    })
    spies.override.mockResolvedValue({
      thread_id: 1,
      title: 'Saga',
      format: 'Comic',
      result: 3,
      issues_remaining: 2,
      queue_position: 1,
      total_issues: 10,
    })
    spies.setDie.mockResolvedValue(undefined)
    spies.clearDie.mockResolvedValue(undefined)
    spies.refetch.mockResolvedValue({})
  })

  it('loads override choices, renders active and snoozed groups, and completes the dice callback', async () => {
    const user = userEvent.setup()
    renderRollPage()

    fireEvent.click(screen.getAllByRole('button', { name: 'complete dice' })[0]!)
    await user.click(screen.getByRole('button', { name: 'Pick manually' }))

    await waitFor(() => expect(spies.list).toHaveBeenCalled())
    const picker = screen.getByRole('combobox')
    await user.click(picker)
    expect(screen.getByRole('option', { name: 'Saga (Comic)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /Watchmen \(Comic\)/ })).toBeInTheDocument()

    await user.click(screen.getByRole('option', { name: 'Saga (Comic)' }))
    await user.click(screen.getByRole('button', { name: 'Open issue card' }))
    expect(spies.override).not.toHaveBeenCalled()
    expect(screen.getByText('Direct issue card for Saga')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Pick manually' })).not.toBeInTheDocument())
  })

  it('opens the manual picker without a pending-offer mutation and retains die selection', async () => {
    state.overridePending = true
    state.manualDie = 6
    const user = userEvent.setup()
    renderRollPage()

    await user.click(screen.getByRole('button', { name: 'Pick manually' }))
    expect(screen.getByRole('button', { name: 'Open issue card' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'close modal' }))
    expect(screen.queryByRole('heading', { name: 'Pick manually' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^current die d6$/i }))
    expect(screen.getByRole('heading', { name: 'Select Die' })).toBeInTheDocument()
    const d8Buttons = screen.getAllByRole('button', { name: 'd8' })
    await user.click(d8Buttons[d8Buttons.length - 1]!)
    await waitFor(() => expect(spies.setDie).toHaveBeenCalledWith(8))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Select Die' })).not.toBeInTheDocument())
  })
})
