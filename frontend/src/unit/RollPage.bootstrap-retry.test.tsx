import { fireEvent, render, screen } from './testingLibrary'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RollPage from '../pages/RollPage'
import { useRollBootstrap } from '../hooks/useRollBootstrap'
import { ToastProvider } from '../contexts/ToastProvider'
import { cast } from '../utils/cast'
import { injectModuleDoubles } from './injectModuleDoubles'
import { MemoryRouter } from 'react-router-dom'
import { NavigationSpy } from './routerTestHarness'

const spies = vi.hoisted(() => ({
  refetch: vi.fn(), navigate: vi.fn(), list: vi.fn(),
}))

await injectModuleDoubles(await import('../contexts/useBugReportRestore'), () => ({
  useBugReportRestore: () => ({ setRestoreAction: vi.fn(), clearRestoreAction: vi.fn() }),
}))
await injectModuleDoubles(await import('../hooks/useRollBootstrap'), () => ({ useRollBootstrap: vi.fn() }))
await injectModuleDoubles(await import('../hooks/useRoll'), () => ({
  useUnsnooze: () => ({ mutate: vi.fn().mockResolvedValue({}), isPending: false }),
  useSetDie: () => ({ mutate: vi.fn(), isPending: false }),
  useResetDice: () => ({ mutate: vi.fn().mockResolvedValue({ die: 6, replayed: false }), isPending: false }),
  useRoll: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissPending: () => ({ mutate: vi.fn(), isPending: false }),
  useOverrideRoll: () => ({ mutate: vi.fn(), isPending: false }),
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
await injectModuleDoubles(await import('../services/api'), () => ({
  default: {},
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
  default: () => <div data-testid="dice" />,
}))
await injectModuleDoubles(await import('../components/Tooltip'), () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
await injectModuleDoubles(await import('../components/GlossaryLink'), () => ({ default: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
await injectModuleDoubles(await import('../components/Modal'), () => ({
  default: ({ isOpen, title, children }: { isOpen: boolean; title: string; children: React.ReactNode }) =>
    isOpen ? <section><h2>{title}</h2>{children}</section> : null,
}))
await injectModuleDoubles(await import('../components/MigrationDialog'), () => ({ default: () => null }))
await injectModuleDoubles(await import('../components/SimpleMigrationDialog'), () => ({ default: () => null }))
await injectModuleDoubles(await import('../pages/RollPage/components/ThreadPool'), () => ({ ThreadPool: () => <div>pool</div> }))

// SAFETY: The mocked useRollBootstrap return value is read by the page hooks;
// the cast reuses the same widening used across the RollPage test suite.
const mockedUseRollBootstrap = cast<ReturnType<typeof vi.fn>>(vi.mocked(useRollBootstrap))

function renderRollPage() {
  return render(
    <ToastProvider>
      <RollPage />
    </ToastProvider>,
  )
}

describe('RollPage bounded bootstrap loading (issue #3429)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    spies.list.mockResolvedValue({ threads: [], next_page_token: null })
    spies.refetch.mockResolvedValue({})
  })

  it('holds a bare spinner before any bootstrap attempt has failed', () => {
    mockedUseRollBootstrap.mockReturnValue({
      data: null,
      refetch: spies.refetch,
      isPending: true,
      isError: false,
      error: null,
      failureCount: 0,
      isRetrying: false,
    })

    renderRollPage()

    expect(screen.getByText('Loading...')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('offers Retry without a reload once a bootstrap attempt has failed', () => {
    mockedUseRollBootstrap.mockReturnValue({
      data: null,
      refetch: spies.refetch,
      isPending: true,
      isError: false,
      error: null,
      failureCount: 1,
      isRetrying: true,
    })

    renderRollPage()

    expect(screen.getByRole('status')).toHaveTextContent('Still loading')
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(spies.refetch).toHaveBeenCalledTimes(1)
  })

  it('offers Retry on a bootstrap failure', () => {
    mockedUseRollBootstrap.mockReturnValue({
      data: null,
      refetch: spies.refetch,
      isPending: false,
      isError: true,
      error: new Error('timeout of 10000ms exceeded'),
      failureCount: 4,
      isRetrying: false,
    })

    renderRollPage()

    expect(screen.getByText('Session Error')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(spies.refetch).toHaveBeenCalledTimes(1)
  })

  it('keeps the bounded loading state visible during a user-initiated retry', () => {
    // React Query resets failureCount to 0 when refetch() starts. The page must
    // stay on the bounded retry affordance instead of falling back to the bare
    // splash the user just clicked Retry to escape.
    mockedUseRollBootstrap.mockReturnValue({
      data: null,
      refetch: spies.refetch,
      isPending: true,
      isError: false,
      error: null,
      failureCount: 0,
      isRetrying: true,
    })

    renderRollPage()

    expect(screen.getByRole('status')).toHaveTextContent('Still loading')
    expect(screen.queryByText('Loading...')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
