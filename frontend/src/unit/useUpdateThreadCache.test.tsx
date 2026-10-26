import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useUpdateThread } from '../hooks/useThread'
import * as cacheEffects from '../query/cacheEffects'
import { threadsApi } from '../services/api-threads'
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
const spyInvalidatePotentialDuplicates = vi.spyOn(cacheEffects, 'invalidatePotentialDuplicates')
const spyInvalidateAfterCreatorCreditChange = vi.spyOn(
  cacheEffects,
  'invalidateAfterCreatorCreditChange',
)

beforeEach(() => {
  spyThreadsApiUpdate.mockReset()
  spyApplyEditedThreadToQueuePages.mockReset()
  spyInvalidatePotentialDuplicates.mockClear()
  spyInvalidateAfterCreatorCreditChange.mockReset()
})

it('publishes the authoritative update through the targeted thread-cache contract', async () => {
  // SAFETY: the updated thread supplies only the fields the cache write asserts
  const updatedThread = {
    id: 7,
    title: 'Updated title',
  } as Thread
  spyThreadsApiUpdate.mockResolvedValue(updatedThread)

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

it('refreshes creator analytics when an update edits manual creator credits (#3461)', async () => {
  // SAFETY: the updated thread supplies only the fields the cache write asserts
  const updatedThread = { id: 7, title: 'Updated title' } as Thread
  spyThreadsApiUpdate.mockResolvedValue(updatedThread)

  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

  await act(async () => {
    await result.current.mutate({
      id: 7,
      data: { manual_creator_credits: [{ name: 'Alan Moore', roles: ['Writer'] }] },
    })
  })

  expect(spyInvalidateAfterCreatorCreditChange).toHaveBeenCalledOnce()
})

it('refreshes advisory duplicate answers after a rename or format edit (#3612)', async () => {
  // SAFETY: the updated thread supplies only the fields the cache write asserts
  const updatedThread = { id: 7, title: 'Spider-Man' } as Thread
  spyThreadsApiUpdate.mockResolvedValue(updatedThread)

  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

  await act(async () => {
    await result.current.mutate({ id: 7, data: { title: 'Spider-Man', format: 'Comic' } })
  })

  // The queue rows are patched in place, but the cached duplicate-check answers
  // from before the rename must stop being served to the Add/Edit forms.
  expect(spyInvalidatePotentialDuplicates).toHaveBeenCalledOnce()
})

it('leaves creator analytics untouched when an update does not change creator credits', async () => {
  // SAFETY: the updated thread supplies only the fields the cache write asserts
  const updatedThread = { id: 7, title: 'Updated title' } as Thread
  spyThreadsApiUpdate.mockResolvedValue(updatedThread)

  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useUpdateThread(), { wrapper })

  await act(async () => {
    await result.current.mutate({ id: 7, data: { title: 'Updated title' } })
  })

  expect(spyInvalidateAfterCreatorCreditChange).not.toHaveBeenCalled()
})
