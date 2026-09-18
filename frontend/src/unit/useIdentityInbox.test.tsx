import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useIdentityInbox,
  useConfirmInboxCandidate,
  useRejectInboxCandidate,
  useDeferInboxItem,
  useSkipInboxItem,
} from '../hooks/useIdentityInbox'
import * as api from '../services/api'
import { queryKeys } from '../query/queryKeys'

vi.mock('../services/api', () => ({
  identityInboxApi: {
    list: vi.fn(),
    confirm: vi.fn(),
    reject: vi.fn(),
    defer: vi.fn(),
    skip: vi.fn(),
  },
}))

const mockedInboxApi = vi.mocked(api.identityInboxApi)

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const inboxResponse = {
  items: [
    {
      mapping_id: 1,
      issue_id: 10,
      thread_id: 100,
      thread_title: 'Mister Miracle',
      issue_number: '1',
      status: 'unresolved',
      provider: 'comicvine',
      source_entry_summary: 'Mister Miracle #1',
      why_stopped: 'No validated local candidate',
      candidates: [],
      created_at: null,
      updated_at: null,
    },
  ],
  total: 1,
  offset: 0,
  limit: 20,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedInboxApi.list.mockResolvedValue(inboxResponse as never)
  mockedInboxApi.confirm.mockResolvedValue(undefined as never)
  mockedInboxApi.reject.mockResolvedValue(undefined as never)
  mockedInboxApi.defer.mockResolvedValue(undefined as never)
  mockedInboxApi.skip.mockResolvedValue(undefined as never)
})

describe('useIdentityInbox', () => {
  it('uses the identityInbox.list query key with correct params', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useIdentityInbox(0), { wrapper })

    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data?.items).toHaveLength(1)
    expect(result.current.data?.total).toBe(1)
    expect(mockedInboxApi.list).toHaveBeenCalledWith(0, 20)
  })

  it('uses different query keys for different offsets', async () => {
    const wrapper = createWrapper()
    const { result: page1 } = renderHook(() => useIdentityInbox(0), { wrapper })
    const { result: page2 } = renderHook(() => useIdentityInbox(20), { wrapper })

    await waitFor(() => expect(page1.current.data).toBeDefined())
    await waitFor(() => expect(page2.current.data).toBeDefined())

    const key1 = queryKeys.identityInbox.list({ offset: 0, limit: 20 })
    const key2 = queryKeys.identityInbox.list({ offset: 20, limit: 20 })
    expect(key1).not.toEqual(key2)
  })
})

describe('useConfirmInboxCandidate', () => {
  it('calls identityInboxApi.confirm with correct args', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useConfirmInboxCandidate(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({
        mappingId: 1,
        payload: { external_identity_id: 501 },
      })
    })

    expect(mockedInboxApi.confirm).toHaveBeenCalledWith(1, {
      external_identity_id: 501,
    })
  })
})

describe('useRejectInboxCandidate', () => {
  it('calls identityInboxApi.reject with correct args', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useRejectInboxCandidate(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({
        mappingId: 1,
        payload: { external_identity_id: 501, rejection_reason: 'Wrong match' },
      })
    })

    expect(mockedInboxApi.reject).toHaveBeenCalledWith(1, {
      external_identity_id: 501,
      rejection_reason: 'Wrong match',
    })
  })
})

describe('useDeferInboxItem', () => {
  it('calls identityInboxApi.defer with correct mappingId', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useDeferInboxItem(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync(42)
    })

    expect(mockedInboxApi.defer).toHaveBeenCalledWith(42)
  })
})

describe('useSkipInboxItem', () => {
  it('calls identityInboxApi.skip with correct mappingId', async () => {
    const wrapper = createWrapper()
    const { result } = renderHook(() => useSkipInboxItem(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync(7)
    })

    expect(mockedInboxApi.skip).toHaveBeenCalledWith(7)
  })
})

describe('query key structure', () => {
  it('identityInbox.all uses correct base key', () => {
    expect(queryKeys.identityInbox.all).toEqual(['identityInbox'])
  })

  it('identityInbox.list normalizes offset and limit into key', () => {
    const key = queryKeys.identityInbox.list({ offset: 0, limit: 20 })
    expect(key).toEqual(['identityInbox', 'list', { offset: 0, limit: 20 }])
  })

  it('identityInbox.list produces distinct keys for different pagination', () => {
    const key1 = queryKeys.identityInbox.list({ offset: 0, limit: 20 })
    const key2 = queryKeys.identityInbox.list({ offset: 20, limit: 20 })
    expect(key1).not.toEqual(key2)
  })
})
