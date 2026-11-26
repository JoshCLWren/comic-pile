import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import CustomCBLBuilder from '../components/CustomCBLBuilder'
import { useUpdateThread } from '../hooks/useThread'
import { notifyThreadMetadataChanged, subscribeToCrossTabChanges } from '../query/crossTabDataSync'
import { queryClient } from '../query/queryClient'
import { issueCardsApi } from '../services/issueCardsApi'
import { cast } from '../utils/cast'
import { isObject } from '../utils/runtimeChecks'
import { existingList } from './fixtures/customCblFixture'

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  updateThread: vi.fn(),
}))

vi.mock('../services/api-custom-cbl', async () => {
  const actual = await vi.importActual<typeof import('../services/api-custom-cbl')>(
    '../services/api-custom-cbl',
  )
  return {
    ...actual,
    customCBLApi: { ...actual.customCBLApi, list: mocks.list, get: mocks.get },
  }
})

vi.mock('../services/api-threads', async () => {
  const actual = await vi.importActual<typeof import('../services/api-threads')>(
    '../services/api-threads',
  )
  return {
    ...actual,
    threadsApi: { ...actual.threadsApi, update: mocks.updateThread },
  }
})

/** Mirrors the browser API: one channel per tab, delivered to every other tab. */
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
        // SAFETY: the fake mirrors the browser API by delivering the payload as event.data.
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

const OLD_TITLE = 'Astro City (2013)'
const NEW_TITLE = 'Astro City (2013) Renamed 20261126'

function listWithTitle(title: string) {
  return {
    ...existingList,
    id: 9,
    issue_count: 1,
    updated_at: '2026-11-26T00:00:00Z',
    entries: [
      {
        id: 91,
        position: 0,
        issue_id: 26360,
        thread_id: 10008446,
        series_name: title,
        issue_number: '13',
        status: 'unread',
        is_checkpoint: false,
        gate: 'none',
        skipped: false,
      },
    ],
  }
}

function newClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: false,
      },
      mutations: { retry: false },
    },
  })
}

function renderBuilder() {
  render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter>
        <CustomCBLBuilder initialListId={9} lockListSelection />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function announceOtherTab(): Promise<void> {
  return act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'thread-metadata-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  FakeBroadcastChannel.reset()
  vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
  vi.spyOn(issueCardsApi, 'fetchCards').mockResolvedValue([])
  mocks.list.mockResolvedValue([
    {
      id: 9,
      name: existingList.name,
      description: existingList.description,
      mode: existingList.mode,
      issue_count: 1,
      updated_at: '2026-11-26T00:00:00Z',
    },
  ])
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('refreshes Reading List titles when another tab renames a Thread (#5862)', async () => {
  mocks.get.mockResolvedValueOnce(listWithTitle(OLD_TITLE))
  mocks.get.mockResolvedValue(listWithTitle(NEW_TITLE))
  renderBuilder()
  expect(await screen.findByLabelText(`Skip ${OLD_TITLE} series in this list`)).toBeInTheDocument()

  await announceOtherTab()

  // The skip control, banner, and issue rows all render the draft's series_name.
  expect(await screen.findByLabelText(`Skip ${NEW_TITLE} series in this list`)).toBeInTheDocument()
  expect(screen.queryByLabelText(`Skip ${OLD_TITLE} series in this list`)).not.toBeInTheDocument()
  expect(screen.queryAllByText(/Astro City \(2013\) #13/)).toHaveLength(0)
  expect(screen.getAllByText(/Renamed 20261126 #13/).length).toBeGreaterThan(0)
  expect(screen.getByText(/Current position: next unread is #1 · .*Renamed 20261126 #13/)).toBeInTheDocument()
  expect(mocks.get).toHaveBeenCalledTimes(2)
})

it('refreshes when the Reading List tab regains focus without BroadcastChannel (#5862)', async () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  mocks.get.mockResolvedValueOnce(listWithTitle(OLD_TITLE))
  mocks.get.mockResolvedValue(listWithTitle(NEW_TITLE))
  renderBuilder()
  expect(await screen.findByLabelText(`Skip ${OLD_TITLE} series in this list`)).toBeInTheDocument()

  await act(async () => {
    window.dispatchEvent(new Event('focus'))
    await Promise.resolve()
  })

  expect(await screen.findByLabelText(`Skip ${NEW_TITLE} series in this list`)).toBeInTheDocument()
  expect(mocks.get).toHaveBeenCalledTimes(2)
})

it('ignores a focus refresh while the tab is hidden (#5862)', async () => {
  mocks.get.mockResolvedValue(listWithTitle(OLD_TITLE))
  renderBuilder()
  expect(await screen.findByLabelText(`Skip ${OLD_TITLE} series in this list`)).toBeInTheDocument()

  const original = Object.getOwnPropertyDescriptor(document, 'visibilityState')
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' })
  try {
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'))
      window.dispatchEvent(new Event('focus'))
      await Promise.resolve()
    })
    expect(mocks.get).toHaveBeenCalledTimes(1)
  } finally {
    if (original) Object.defineProperty(document, 'visibilityState', original)
  }
})

it('keeps unsaved skip edits while reconciling the canonical title (#5862)', async () => {
  mocks.get.mockResolvedValueOnce(listWithTitle(OLD_TITLE))
  mocks.get.mockResolvedValue(listWithTitle(NEW_TITLE))
  renderBuilder()
  fireEvent.click(await screen.findByLabelText(`Skip ${OLD_TITLE} series in this list`))
  expect(screen.getByLabelText(`Skip ${OLD_TITLE} series in this list`)).toBeChecked()

  await announceOtherTab()

  // The rename must not discard a local edit or silently save it.
  expect(await screen.findByLabelText(`Skip ${NEW_TITLE} series in this list`)).toBeChecked()
  expect(mocks.updateThread).not.toHaveBeenCalled()
})

it('announces a committed Thread rename before this tab finishes its own refresh (#5862)', async () => {
  mocks.updateThread.mockResolvedValue({ id: 10008446, title: NEW_TITLE })
  const changes: string[] = []
  const observer = new BroadcastChannel('comic-pile-data')
  observer.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data
    if (isObject(data) && 'type' in data) {
      // SAFETY: the 'in' guard above confirms the payload carries a type field.
      changes.push(String((data as { type: unknown }).type))
    }
  })
  let finishLocalRefresh: () => void = () => undefined
  const localRefresh = new Promise<void>((resolve) => {
    finishLocalRefresh = resolve
  })
  // useUpdateThread applies its cache effects to the app-wide singleton.
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries').mockReturnValueOnce(localRefresh)
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={newClient()}>{children}</QueryClientProvider>
  )
  const { result } = renderHook(() => useUpdateThread(), { wrapper })
  let pending: Promise<unknown> = Promise.resolve()

  await act(async () => {
    pending = result.current.mutate({ id: 10008446, data: { title: NEW_TITLE } })
    await Promise.resolve()
  })
  await waitFor(() => expect(invalidateSpy).toHaveBeenCalled())

  // The other tab learns about the rename while this tab's refetch is pending.
  expect(changes).toEqual(['thread-metadata-changed'])
  await act(async () => {
    finishLocalRefresh()
    await pending
  })
  observer.close()
})

it('does not announce a Thread edit that leaves metadata unchanged (#5862)', async () => {
  mocks.updateThread.mockResolvedValue({ id: 10008446, notes: 'not a rename' })
  const changes: string[] = []
  const observer = new BroadcastChannel('comic-pile-data')
  observer.addEventListener('message', (event: MessageEvent<unknown>) => {
    const data = event.data
    if (isObject(data) && 'type' in data) {
      // SAFETY: the 'in' guard above confirms the payload carries a type field.
      changes.push(String((data as { type: unknown }).type))
    }
  })
  const { result } = renderHook(() => useUpdateThread(), {
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={newClient()}>{children}</QueryClientProvider>
    ),
  })

  await act(async () => {
    await result.current.mutate({ id: 10008446, data: { notes: 'not a rename' } })
  })

  expect(changes).toEqual([])
  observer.close()
})

it('ignores its own broadcast so the writing tab does not refresh twice (#5862)', async () => {
  const changes: string[] = []
  const unsubscribe = subscribeToCrossTabChanges((change) => changes.push(change.type))

  await act(async () => {
    notifyThreadMetadataChanged()
    await Promise.resolve()
  })

  expect(changes).toEqual([])
  unsubscribe()
})

it('keeps cross-tab sync best-effort when BroadcastChannel is unavailable or blocked (#5862)', () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  const listener = vi.fn()
  expect(() => notifyThreadMetadataChanged()).not.toThrow()
  expect(subscribeToCrossTabChanges(listener)()).toBeUndefined()

  class BlockedBroadcastChannel {
    constructor() {
      throw new Error('BroadcastChannel blocked')
    }
  }
  vi.stubGlobal('BroadcastChannel', BlockedBroadcastChannel)
  expect(() => notifyThreadMetadataChanged()).not.toThrow()
  expect(subscribeToCrossTabChanges(listener)()).toBeUndefined()
  expect(listener).not.toHaveBeenCalled()
})

it('ignores malformed and unrelated cross-tab messages (#5862)', () => {
  const listener = vi.fn()
  const unsubscribe = subscribeToCrossTabChanges(listener)
  const otherTab = new BroadcastChannel('comic-pile-data')

  for (const data of [
    null,
    {},
    { type: 42, senderId: 'other-tab' },
    { type: 'thread-metadata-changed' },
    { type: 'unrelated-change', senderId: 'other-tab' },
  ]) {
    otherTab.postMessage(data)
  }

  expect(listener).not.toHaveBeenCalled()
  otherTab.close()
  unsubscribe()
})

it('does not refetch a Reading List for an unrelated cross-tab change (#5862)', async () => {
  mocks.get.mockResolvedValue(listWithTitle(OLD_TITLE))
  renderBuilder()
  await screen.findByLabelText(`Skip ${OLD_TITLE} series in this list`)

  await act(async () => {
    const otherTab = new BroadcastChannel('comic-pile-data')
    otherTab.postMessage({ type: 'reading-plans-changed', senderId: 'other-tab' })
    otherTab.close()
    await Promise.resolve()
  })

  expect(mocks.get).toHaveBeenCalledTimes(1)
  expect(cast<ReturnType<typeof vi.fn>>(mocks.get).mock.calls).toHaveLength(1)
})
