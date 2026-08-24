import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useUpdateThread } from '../hooks/useThread'
import { applyEditedThreadToQueuePages } from '../query/cacheEffects'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

function createTestWrapper() {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

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

  const { client, wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

  let returnedThread: Thread | undefined
  await act(async () => {
    returnedThread = await result.current.mutate({
      id: 7,
      data: { title: 'Updated title' },
    })
  })

  expect(mockedThreadsApi.update).toHaveBeenCalledWith(7, { title: 'Updated title' })
  expect(mockedApplyEditedThreadToQueuePages).toHaveBeenCalledOnce()
  expect(mockedApplyEditedThreadToQueuePages).toHaveBeenCalledWith(client, updatedThread)
  expect(returnedThread).toBe(updatedThread)
  expect(result.current.isError).toBe(false)
  expect(result.current.isPending).toBe(false)
})

it('does not touch targeted cache state when the update request fails', async () => {
  const failure = new Error('update failed')
  mockedThreadsApi.update.mockRejectedValue(failure)

  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

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
