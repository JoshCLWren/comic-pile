import { act, render, renderHook, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { useQueueModals } from '../pages/QueuePage/useQueueModals'
import { DEFAULT_CREATE_STATE } from '../pages/QueuePage/types'
import { ToastProvider } from '../contexts/ToastProvider'
import type { ThreadListItem } from '../types'

vi.mock('../contexts/useBugReportRestore', () => ({
  useBugReportRestore: () => ({
    setRestoreAction: vi.fn(),
    clearRestoreAction: vi.fn(),
  }),
}))

vi.mock('../components/QueueMapSeriesDialog', () => ({
  default: ({ thread }: { thread: ThreadListItem }) => (
    <div data-testid="mock-map-series-dialog" data-thread-id={thread.id} />
  ),
}))

function createThread(): ThreadListItem {
  // SAFETY: Test data matches ThreadListItem shape exactly
  return {
    id: 10,
    title: 'Saga',
    format: 'Comic',
    issues_remaining: 2,
    queue_position: 1,
    status: 'active',
    last_activity_at: null,
    is_blocked: false,
    blocking_reasons: [],
    total_issues: 12,
    next_unread_issue_number: '11',
    notes: null,
    created_at: '2024-01-01T00:00:00.000Z',
  } as ThreadListItem
}

function modalsProps(overrides = {}) {
  const noop = () => Promise.resolve()
  return {
    openModal: null,
    createForm: DEFAULT_CREATE_STATE,
    editForm: DEFAULT_CREATE_STATE,
    setCreateForm: vi.fn(),
    setEditForm: vi.fn(),
    issuePreview: null,
    issueParseError: null,
    editingThread: null,
    repositioningThread: null,
    dependencyThread: null,
    threadToMigrate: null,
    showMigrationDialog: false,
    reactivateThreadId: '',
    setReactivateThreadId: vi.fn(),
    issuesToAdd: 1,
    setIssuesToAdd: vi.fn(),
    activeThreads: [],
    completedThreads: [],
    queueSize: 0,
    onCreateSubmit: noop,
    onEditSubmit: noop,
    onReactivateSubmit: noop,
    onRepositionConfirm: noop,
    onDependencyChanged: noop,
    onCloseCreate: vi.fn(),
    onCloseEdit: vi.fn(),
    onCloseReactivate: vi.fn(),
    onCloseReposition: vi.fn(),
    onCloseDependency: vi.fn(),
    onMigrationComplete: noop,
    onMigrationSkip: vi.fn(),
    onCloseMigration: vi.fn(),
    onOpenMigrationDialog: vi.fn(),
    isPendingCreate: false,
    isPendingEdit: false,
    isPendingReactivate: false,
    showRollNudge: false,
    onDismissRollNudge: vi.fn(),
    onRollNudgeNavigate: vi.fn(),
    ...overrides,
  }
}

function hookParams(overrides = {}) {
  const noop = () => Promise.resolve()
  return {
    threads: [],
    onCreated: noop,
    onUpdated: noop,
    onReactivated: noop,
    refetchSession: noop,
    submitCreate: vi.fn().mockResolvedValue({}),
    submitEdit: vi.fn(),
    submitReactivate: vi.fn(),
    isPendingCreate: false,
    isPendingEdit: false,
    showRollNudge: false,
    onDismissRollNudge: vi.fn(),
    onRollNudgeNavigate: vi.fn(),
    ...overrides,
  }
}

describe('QueueModals map series wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mounts the repair dialog only while a thread is selected', () => {
    const onClose = vi.fn()
    const renderModals = (props: React.ComponentProps<typeof QueueModals>) =>
      render(
        <ToastProvider>
          <QueueModals {...props} />
        </ToastProvider>,
      )
    const { rerender } = renderModals({
      ...modalsProps(),
      mapSeries: { thread: createThread(), onClose },
    })

    expect(screen.getByTestId('mock-map-series-dialog')).toHaveAttribute('data-thread-id', '10')

    rerender(
      <ToastProvider>
        <QueueModals {...modalsProps()} mapSeries={{ thread: null, onClose }} />
      </ToastProvider>,
    )
    expect(screen.queryByTestId('mock-map-series-dialog')).not.toBeInTheDocument()
  })

  it('renders no repair dialog when the prop is omitted', () => {
    render(
      <ToastProvider>
        <QueueModals {...modalsProps()} />
      </ToastProvider>,
    )

    expect(screen.queryByTestId('mock-map-series-dialog')).not.toBeInTheDocument()
  })
})

describe('useQueueModals map series state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  function renderModalsHook() {
    return renderHook(() => useQueueModals(hookParams()), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <MemoryRouter>{children}</MemoryRouter>
      ),
    })
  }

  it('opens and closes the repair selection without touching other modals', () => {
    const { result } = renderModalsHook()
    const thread = createThread()

    expect(result.current.mapSeriesThread).toBeNull()
    expect(result.current.isAnyModalOpen).toBe(false)

    act(() => {
      result.current.openMapSeries(thread)
    })

    expect(result.current.mapSeriesThread).toBe(thread)
    expect(result.current.isAnyModalOpen).toBe(true)
    expect(result.current.openModal).toBeNull()

    act(() => {
      result.current.closeMapSeries()
    })

    expect(result.current.mapSeriesThread).toBeNull()
  })
})
