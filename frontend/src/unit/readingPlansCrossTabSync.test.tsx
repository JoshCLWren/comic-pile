import { act, render, renderHook, screen, waitFor } from './testingLibrary'
import { QueryClient } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useDeleteReadingPlan, useSaveReadingPlan } from '../hooks/useReadingPlans'
import ContinuityPlansIndexPage from '../pages/ContinuityPlansIndexPage'
import { applyCommittedReadingPlan } from '../query/cacheEffects'
import { notifyReadingPlansChanged, subscribeToCrossTabChanges } from '../query/crossTabDataSync'
import { queryClient } from '../query/queryClient'
import { cast } from '../utils/cast'
import { isObject } from '../utils/runtimeChecks'
import { injectModuleDoubles } from './injectModuleDoubles'

const mocks = {
  list: vi.fn(),
  update: vi.fn(),
  delete: vi.fn(),
}

await injectModuleDoubles(await import('../services/api-continuity-plans'), async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/api-continuity-plans')>()
  return {
    continuityPlansApi: {
      ...actual.continuityPlansApi,
      list: mocks.list,
      update: mocks.update,
      delete: mocks.delete,
    },
  }
})

const mockList = mocks.list
const mockUpdate = mocks.update
const mockDelete = mocks.delete

const plan = {
  id: 1,
  name: 'QA-F-Order',
  ordering_mode: 'informational',
  lane_count: 1,
  step_count: 3,
  // SAFETY: this fixture declares no source paths
  source_paths: [] as string[],
  updated_at: '2026-11-22T00:00:00Z',
}

const planWrite = {
  name: 'QA-F-Order-TwoTab',
  ordering_mode: 'informational' as const,
  lanes: [],
  nodes: [],
}

/**
 * Stand-in for the browser's BroadcastChannel: one instance per tab, messages
 * delivered to every other instance with the same channel name (never back to
 * the sender), matching the real API this fix relies on.
 */
class FakeBroadcastChannel {
  static channels = new Set<FakeBroadcastChannel>()

  readonly name: string
  private readonly listeners = new Set<(event: MessageEvent<unknown>) => void>()

  constructor(name: string) {
    this.name = name
    FakeBroadcastChannel.channels.add(this)
  }

  addEventListener(type: string, listener: (event: MessageEvent<unknown>) => void): void {
    if (type === 'message') this.listeners.add(listener)
  }

  removeEventListener(type: string, listener: (event: MessageEvent<unknown>) => void): void {
    if (type === 'message') this.listeners.delete(listener)
  }

  postMessage(data: unknown): void {
    for (const channel of FakeBroadcastChannel.channels) {
      if (channel === this || channel.name !== this.name) continue
      for (const listener of [...channel.listeners]) {
        // SAFETY: the fake mirrors the browser API by delivering the posted payload as event.data.
        listener({ data } as MessageEvent<unknown>)
      }
    }
  }

  close(): void {
    FakeBroadcastChannel.channels.delete(this)
    this.listeners.clear()
  }

  static reset(): void {
    FakeBroadcastChannel.channels.clear()
  }
}

function renderPlansIndex() {
  return render(
    <MemoryRouter>
      <ContinuityPlansIndexPage />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  FakeBroadcastChannel.reset()
  vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('refreshes the plans list when another tab renames a plan (#5686)', async () => {
  mockList.mockResolvedValueOnce([plan])
  mockList.mockResolvedValue([{ ...plan, name: 'QA-F-Order-TwoTab' }])
  renderPlansIndex()
  expect(await screen.findByText('QA-F-Order')).toBeInTheDocument()

  // Another tab commits the rename and announces it. No reload, timer, or
  // staleTime expiry is part of this reproduction. Post with a different
  // senderId so the subscriber treats it as cross-tab, not a same-tab echo.
  await act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'reading-plans-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })

  expect(await screen.findByText('QA-F-Order-TwoTab')).toBeInTheDocument()
  expect(screen.queryByText('QA-F-Order')).not.toBeInTheDocument()
  expect(mockList).toHaveBeenCalledTimes(2)
})

it('supersedes an initial list request when another tab changes a plan (#5686)', async () => {
  let finishInitial: (plans: Array<typeof plan>) => void = () => undefined
  const initialRequest = new Promise<Array<typeof plan>>((resolve) => {
    finishInitial = resolve
  })
  mockList.mockReturnValueOnce(initialRequest)
  mockList.mockResolvedValue([{ ...plan, name: 'QA-F-Order-Fresh' }])
  renderPlansIndex()
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1))

  await act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'reading-plans-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })

  // The fresh request must start before the stale initial request settles.
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  expect(await screen.findByText('QA-F-Order-Fresh')).toBeInTheDocument()

  await act(async () => {
    finishInitial([plan])
    await initialRequest
  })
  expect(screen.getByText('QA-F-Order-Fresh')).toBeInTheDocument()
  expect(screen.queryByText('QA-F-Order')).not.toBeInTheDocument()
})

it('supersedes an initial list request on visibility without BroadcastChannel (#5686)', async () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  let finishInitial: (plans: Array<typeof plan>) => void = () => undefined
  const initialRequest = new Promise<Array<typeof plan>>((resolve) => {
    finishInitial = resolve
  })
  mockList.mockReturnValueOnce(initialRequest)
  mockList.mockResolvedValue([{ ...plan, name: 'QA-F-Order-Visible' }])
  renderPlansIndex()
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(1))

  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()
  })

  // Focus recovery must not join a request that started before the remote commit.
  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  expect(await screen.findByText('QA-F-Order-Visible')).toBeInTheDocument()

  await act(async () => {
    finishInitial([plan])
    await initialRequest
  })
  expect(screen.getByText('QA-F-Order-Visible')).toBeInTheDocument()
  expect(screen.queryByText('QA-F-Order')).not.toBeInTheDocument()
})

it('reconciles the plans list when another tab creates a plan (#5686)', async () => {
  const created = { ...plan, id: 2, name: 'QA-F-Order-New' }
  mockList.mockResolvedValueOnce([plan])
  mockList.mockResolvedValue([plan, created])
  renderPlansIndex()
  expect(await screen.findByText('QA-F-Order')).toBeInTheDocument()
  expect(screen.queryByText('QA-F-Order-New')).not.toBeInTheDocument()

  // The add happens in another tab; the list must gain the new plan without a
  // manual reload (issue #5686 acceptance: "Same for adding ... a plan").
  await act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'reading-plans-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })

  expect(await screen.findByText('QA-F-Order-New')).toBeInTheDocument()
  expect(mockList).toHaveBeenCalledTimes(2)
})

it('reconciles the plans list when another tab deletes a plan (#5686)', async () => {
  mockList.mockResolvedValueOnce([plan])
  mockList.mockResolvedValue([])
  renderPlansIndex()
  expect(await screen.findByText('QA-F-Order')).toBeInTheDocument()

  // The delete happens in another tab; the list must drop the plan without a
  // manual reload (issue #5686 acceptance: "Same for ... deleting a plan").
  await act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'reading-plans-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })

  await waitFor(() => expect(mockList).toHaveBeenCalledTimes(2))
  expect(screen.queryByText('QA-F-Order')).not.toBeInTheDocument()
})

it('refreshes the plans list when the tab regains focus (#5686)', async () => {
  mockList.mockResolvedValueOnce([plan])
  mockList.mockResolvedValue([{ ...plan, name: 'QA-F-Order-Focused' }])
  renderPlansIndex()
  expect(await screen.findByText('QA-F-Order')).toBeInTheDocument()

  await act(async () => {
    window.dispatchEvent(new Event('focus'))
    await Promise.resolve()
  })

  expect(await screen.findByText('QA-F-Order-Focused')).toBeInTheDocument()
  expect(mockList).toHaveBeenCalledTimes(2)
})

it('ignores focus refresh when the tab is hidden (#5686)', async () => {
  mockList.mockResolvedValueOnce([plan])
  renderPlansIndex()
  expect(await screen.findByText('QA-F-Order')).toBeInTheDocument()

  const original = Object.getOwnPropertyDescriptor(document, 'visibilityState')
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
  try {
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('focus'))
      await Promise.resolve()
    })
    expect(mockList).toHaveBeenCalledTimes(1)
  } finally {
    if (original) Object.defineProperty(document, 'visibilityState', original)
  }
})

it('announces a committed plan delete to other tabs (#5686)', async () => {
  mockDelete.mockResolvedValue(undefined)
  const changes: string[] = []
  const observer = new BroadcastChannel('comic-pile-data')
  observer.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data
    if (isObject(data) && 'type' in data) {
      // SAFETY: the 'in' guard above confirms the broadcast payload carries a type field.
      changes.push(String((data as { type: unknown }).type))
    }
  })
  let finishLocalRefresh: () => void = () => undefined
  const localRefresh = new Promise<void>((resolve) => {
    finishLocalRefresh = resolve
  })
  const invalidateSpy = vi
    .spyOn(queryClient, 'invalidateQueries')
    .mockReturnValueOnce(localRefresh)
  const { result } = renderHook(() => useDeleteReadingPlan())
  let deletion: Promise<void> = Promise.resolve()

  await act(async () => {
    deletion = result.current.mutateAsync(1)
    await Promise.resolve()
  })
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalled())

  // The other tab is notified while this tab's local refresh is still pending.
  expect(changes).toEqual(['reading-plans-changed'])
  await act(async () => {
    finishLocalRefresh()
    await deletion
  })
  observer.close()
})

it('announces a committed plan save to other tabs (#5686)', async () => {
  mockUpdate.mockResolvedValue({
    ...plan,
    ...planWrite,
    user_id: 1,
    created_at: '2026-11-01T00:00:00Z',
    lanes: [],
    nodes: [],
  })
  const changes: string[] = []
  const observer = new BroadcastChannel('comic-pile-data')
  observer.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data
    if (isObject(data) && 'type' in data) {
      // SAFETY: the 'in' guard above confirms the broadcast payload carries a type field.
      changes.push(String((data as { type: unknown }).type))
    }
  })
  const { result } = renderHook(() => useSaveReadingPlan(1))

  await act(async () => {
    await result.current.mutateAsync(planWrite)
  })

  expect(changes).toEqual(['reading-plans-changed'])
  observer.close()
})

it('ignores its own broadcast so the writing tab does not refresh twice (#5686 G2)', async () => {
  const changes: string[] = []
  const unsubscribe = subscribeToCrossTabChanges((change) => changes.push(change.type))

  await act(async () => {
    notifyReadingPlansChanged()
    await Promise.resolve()
  })

  expect(changes).toEqual([])
  unsubscribe()
})

it('keeps plan sync best-effort when BroadcastChannel is unavailable (#5686)', () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  const listener = vi.fn()

  expect(() => notifyReadingPlansChanged()).not.toThrow()
  const unsubscribe = subscribeToCrossTabChanges(listener)
  expect(listener).not.toHaveBeenCalled()
  unsubscribe()
})

it('keeps plan sync best-effort when the browser blocks BroadcastChannel (#5686)', () => {
  class BlockedBroadcastChannel {
    constructor() {
      throw new Error('BroadcastChannel blocked')
    }
  }
  vi.stubGlobal('BroadcastChannel', BlockedBroadcastChannel)
  const listener = vi.fn()

  expect(() => notifyReadingPlansChanged()).not.toThrow()
  const unsubscribe = subscribeToCrossTabChanges(listener)
  expect(listener).not.toHaveBeenCalled()
  unsubscribe()
})

it('keeps plan sync best-effort when posting a change fails (#5686)', () => {
  class FailingBroadcastChannel extends FakeBroadcastChannel {
    override postMessage(_data: unknown): void {
      throw new Error('postMessage blocked')
    }
  }
  vi.stubGlobal('BroadcastChannel', FailingBroadcastChannel)

  expect(() => notifyReadingPlansChanged()).not.toThrow()
  expect(FakeBroadcastChannel.channels.size).toBe(0)
})

it('ignores malformed and unrelated cross-tab messages (#5686)', () => {
  const listener = vi.fn()
  const unsubscribe = subscribeToCrossTabChanges(listener)
  const otherTab = new BroadcastChannel('comic-pile-data')

  for (const data of [
    null,
    {},
    { type: 42, senderId: 'other-tab' },
    { type: 'reading-plans-changed' },
    { type: 'unrelated-change', senderId: 'other-tab' },
  ]) {
    otherTab.postMessage(data)
  }

  expect(listener).not.toHaveBeenCalled()
  otherTab.close()
  unsubscribe()
})

it('announces a committed plan adoption to other tabs (#5686 G1)', async () => {
  const changes: string[] = []
  const observer = new BroadcastChannel('comic-pile-data')
  observer.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data
    if (isObject(data) && 'type' in data) {
      // SAFETY: the 'in' guard above confirms the broadcast payload carries a type field.
      changes.push(String((data as { type: unknown }).type))
    }
  })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  let finishLocalRefresh: () => void = () => undefined
  const localRefresh = new Promise<void>((resolve) => {
    finishLocalRefresh = resolve
  })
  const invalidateSpy = vi.spyOn(client, 'invalidateQueries').mockReturnValueOnce(localRefresh)
  let commit: Promise<void> = Promise.resolve()

  await act(async () => {
    commit = applyCommittedReadingPlan(
      client,
      cast<Parameters<typeof applyCommittedReadingPlan>[1]>({
        id: 1,
        name: 'Plan',
        ordering_mode: 'informational',
        lane_count: 0,
        step_count: 0,
        source_paths: [],
        updated_at: plan.updated_at,
      }),
    )
    await Promise.resolve()
  })
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalled())

  // Save/adoption publishes before awaiting potentially slow local refetches.
  expect(changes).toEqual(['reading-plans-changed'])
  await act(async () => {
    finishLocalRefresh()
    await commit
  })
  observer.close()
  client.clear()
})
