import { act, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { FormEvent, ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { BugReportRestoreProvider } from '../contexts/BugReportRestoreContext'
import { QueueModals } from '../pages/QueuePage/QueueModals'
import { DEFAULT_CREATE_STATE } from '../pages/QueuePage/types'
import { useQueueModals } from '../pages/QueuePage/useQueueModals'
import { createThreadsApi } from '../services/api-threads'

vi.mock('../components/Modal', () => ({
  default: ({
    isOpen,
    title,
    children,
  }: {
    isOpen: boolean
    title: string
    children: ReactNode
  }) => (isOpen ? <section aria-label={title}>{children}</section> : null),
}))

vi.mock('../components/PositionSlider', () => ({
  default: () => null,
}))

vi.mock('../components/DependencyBuilder', () => ({
  default: () => null,
}))

vi.mock('../components/MigrationDialog', () => ({
  default: () => null,
}))

vi.mock('../pages/QueuePage/IssueToggleList', () => ({
  IssueToggleList: () => null,
}))

vi.mock('../pages/QueuePage/FormatSelect', () => ({
  FormatSelect: ({
    id,
    value,
    onChange,
  }: {
    id: string
    value: string
    onChange: (value: string) => void
  }) => (
    <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="Comic">Comic</option>
    </select>
  ),
}))

function modalProps(overrides: { isPendingCreate: boolean }) {
  return {
    openModal: 'create' as const,
    createForm: { ...DEFAULT_CREATE_STATE, title: 'Saga', issues: '1-3' },
    editForm: DEFAULT_CREATE_STATE,
    setCreateForm: vi.fn(),
    setEditForm: vi.fn(),
    issuePreview: 3,
    issueParseError: null,
    issueParseWarnings: [],
    issueParseBreakdown: [],
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
    onCreateSubmit: vi.fn(async (event: FormEvent) => event.preventDefault()),
    onEditSubmit: vi.fn(async (event: FormEvent) => event.preventDefault()),
    onReactivateSubmit: vi.fn(async (event: FormEvent) => event.preventDefault()),
    onRepositionConfirm: vi.fn(),
    onDependencyChanged: vi.fn(async () => undefined),
    onCloseCreate: vi.fn(),
    onCloseEdit: vi.fn(),
    onCloseReactivate: vi.fn(),
    onCloseReposition: vi.fn(),
    onCloseDependency: vi.fn(),
    onMigrationComplete: vi.fn(async () => undefined),
    onMigrationSkip: vi.fn(),
    onCloseMigration: vi.fn(),
    onOpenMigrationDialog: vi.fn(),
    onCloseAddSeriesComicVine: vi.fn(),
    isPendingCreate: overrides.isPendingCreate,
    isPendingEdit: false,
    isPendingReactivate: false,
    showRollNudge: false,
    onDismissRollNudge: vi.fn(),
    onRollNudgeNavigate: vi.fn(),
  }
}

describe('Create Series double-submit guard (#3466)', () => {
  it('disables Create Series and shows progress while the request is in flight', () => {
    const { rerender } = render(<QueueModals {...modalProps({ isPendingCreate: false })} />)
    const idleButton = screen.getByRole('button', { name: 'Create Series' })
    expect(idleButton).toBeEnabled()

    rerender(<QueueModals {...modalProps({ isPendingCreate: true })} />)
    const pendingButton = screen.getByRole('button', { name: 'Adding...' })
    expect(pendingButton).toBeDisabled()
  })

  it('double-clicking Create Series submits exactly once while pending', async () => {
    const user = userEvent.setup()
    const onCreateSubmit = vi.fn(async (event: FormEvent) => event.preventDefault())
    const { rerender } = render(
      <QueueModals {...modalProps({ isPendingCreate: false })} onCreateSubmit={onCreateSubmit} />,
    )

    await user.click(screen.getByRole('button', { name: 'Create Series' }))
    expect(onCreateSubmit).toHaveBeenCalledTimes(1)

    // From the first click until the response arrives the button is disabled
    // with progress, so the second click of a double-click cannot resubmit.
    rerender(
      <QueueModals {...modalProps({ isPendingCreate: true })} onCreateSubmit={onCreateSubmit} />,
    )
    const pendingButton = screen.getByRole('button', { name: 'Adding...' })
    expect(pendingButton).toBeDisabled()
    await user.click(pendingButton).catch(() => undefined)
    expect(onCreateSubmit).toHaveBeenCalledTimes(1)
  })

  it('drops a same-tick second submit and reuses one idempotency key', async () => {
    window.alert = vi.fn()
    let resolveCreate!: (value: { id: number }) => void
    const submitCreate = vi.fn(
      () =>
        new Promise<{ id: number }>((resolve) => {
          resolveCreate = resolve
        }),
    )
    const wrapper = ({ children }: { children: ReactNode }) => (
      <MemoryRouter>
        <BugReportRestoreProvider>{children}</BugReportRestoreProvider>
      </MemoryRouter>
    )
    const { result } = renderHook(
      () =>
        useQueueModals({
          threads: [],
          onCreated: vi.fn(async () => undefined),
          onUpdated: vi.fn(async () => undefined),
          onReactivated: vi.fn(async () => undefined),
          refetchSession: vi.fn(async () => undefined),
          submitCreate,
          submitEdit: vi.fn(async () => ({ id: 1 }) as never),
          submitReactivate: vi.fn(async () => ({ id: 1 }) as never),
          isPendingCreate: false,
          isPendingEdit: false,
          showRollNudge: false,
          onDismissRollNudge: vi.fn(),
          onRollNudgeNavigate: vi.fn(),
        }),
      { wrapper },
    )

    act(() => {
      result.current.showCreateModal()
    })
    act(() => {
      result.current.setCreateForm({
        ...DEFAULT_CREATE_STATE,
        title: 'Double Click Series',
        issues: '',
        issuesRemaining: 5,
      })
    })

    const fakeEvent = () => ({ preventDefault: vi.fn() }) as unknown as FormEvent
    let first!: Promise<void>
    let second!: Promise<void>
    act(() => {
      first = result.current.handleCreateSubmit(fakeEvent())
      second = result.current.handleCreateSubmit(fakeEvent())
    })
    await waitFor(() => expect(submitCreate).toHaveBeenCalledTimes(1))
    const key = (submitCreate.mock.calls[0][0] as { idempotency_key?: string }).idempotency_key
    expect(key).toBeTruthy()

    act(() => {
      resolveCreate({ id: 7 })
    })
    await act(async () => {
      await first
      await second
    })
    expect(submitCreate).toHaveBeenCalledTimes(1)
  })

  it('sends the idempotency key as both body field and Idempotency-Key header', async () => {
    const post = vi.fn(async () => ({ id: 1 }))
    const client = {
      get: vi.fn(),
      delete: vi.fn(),
      post,
      put: vi.fn(),
      patch: vi.fn(),
    }
    const api = createThreadsApi(client)
    await api.create({
      title: 'Saga',
      format: 'Comic',
      issues_remaining: 3,
      idempotency_key: 'key-3466-frontend',
    })
    expect(post).toHaveBeenCalledTimes(1)
    expect(post.mock.calls[0][1]).toMatchObject({ idempotency_key: 'key-3466-frontend' })
    expect(post.mock.calls[0][2]).toMatchObject({ headers: { 'Idempotency-Key': 'key-3466-frontend' } })
  })
})
