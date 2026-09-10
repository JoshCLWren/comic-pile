import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useUpdateThread } from '../hooks/useThread'
import * as cacheEffects from '../query/cacheEffects'
import { threadsApi } from '../services/api'
import type { Thread } from '../types'

function createTestWrapper() {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

const spyThreadsApiUpdate = vi.spyOn(threadsApi, 'update')
const spyApplyEditedThreadToQueuePages = vi.spyOn(cacheEffects, 'applyEditedThreadToQueuePages')

beforeEach(() => {
  spyThreadsApiUpdate.mockReset()
  spyApplyEditedThreadToQueuePages.mockReset()
})

it('publishes the authoritative update through the targeted thread-cache contract', async () => {
  const updatedThread = {
    id: 7,
    title: 'Updated title',
  } as Thread
  spyThreadsApiUpdate.mockResolvedValue(updatedThread as never)

  const { client, wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

  let returnedThread: Thread | undefined
  await act(async () => {
    returnedThread = await result.current.mutate({
      id: 7,
      data: { title: 'Updated title' },
    })
  })

  expect(spyThreadsApiUpdate).toHaveBeenCalledWith(7, { title: 'Updated title' })
  expect(spyApplyEditedThreadToQueuePages).toHaveBeenCalledOnce()
  expect(spyApplyEditedThreadToQueuePages).toHaveBeenCalledWith(client, updatedThread)
  expect(returnedThread).toBe(updatedThread)
  expect(result.current.isError).toBe(false)
  expect(result.current.isPending).toBe(false)
})

it('does not touch targeted cache state when the update request fails', async () => {
  const failure = new Error('update failed')
  spyThreadsApiUpdate.mockRejectedValue(failure)

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
  expect(spyApplyEditedThreadToQueuePages).not.toHaveBeenCalled()
  await waitFor(() => expect(result.current.isError).toBe(true))
  expect(result.current.isPending).toBe(false)
})