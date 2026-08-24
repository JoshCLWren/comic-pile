import { act, renderHook, waitFor } from '@testing-library/react'
import type { PropsWithChildren } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, expect, it, vi } from 'vitest'
import { useUpdateThread } from '../hooks/useThread'
import { applyEditedThreadToQueuePages } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

vi.mock('../services/api', () => ({
  threadsApi: {
    update: vi.fn(),
  },
}))

vi.mock('../query/cacheEffects', () => ({
  applyEditedThreadToQueuePages: vi.fn(),
}))

const mockedThreadsApi = vi.mocked(threadsApi)
const mockedApplyEditedThreadToQueuePages = vi.mocked(applyEditedThreadToQueuePages)

function renderHookWithClient<T>(hook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return renderHook(hook, {
    wrapper: ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

beforeEach(() => {
  mockedThreadsApi.update.mockReset()
  mockedApplyEditedThreadToQueuePages.mockReset()
})

it('publishes the authoritative update through the targeted thread-cache contract', async () => {
  const updatedThread = {
    id: 7,
    title: 'Updated title',
  } as Thread
  mockedThreadsApi.update.mockResolvedValue(updatedThread)

  const { result } = renderHookWithClient(() => useUpdateThread())

  let returnedThread: Thread | undefined
  await act(async () => {
    returnedThread = await result.current.mutate({
      id: 7,
      data: { title: 'Updated title' },
    })
  })

  expect(mockedThreadsApi.update).toHaveBeenCalledWith(7, { title: 'Updated title' })
  expect(mockedApplyEditedThreadToQueuePages).toHaveBeenCalledOnce()
  expect(mockedApplyEditedThreadToQueuePages).toHaveBeenCalledWith(queryClient, updatedThread)
  expect(returnedThread).toBe(updatedThread)
  expect(result.current.isError).toBe(false)
  expect(result.current.isPending).toBe(false)
})

it('does not touch targeted cache state when the update request fails', async () => {
  const failure = new Error('update failed')
  mockedThreadsApi.update.mockRejectedValue(failure)

  const { result } = renderHookWithClient(() => useUpdateThread())

  let caught: unknown
  await act(async () => {
    try {
      await result.current.mutate({
        id: 7,
        data: { title: 'Never saved' },
      })
    } catch (error) {
      caught = error
    }
  })

  expect(caught).toBe(failure)
  expect(mockedApplyEditedThreadToQueuePages).not.toHaveBeenCalled()
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(result.current.isPending).toBe(false)
})
