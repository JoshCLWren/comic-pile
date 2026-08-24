import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type ReactNode } from 'react'
import { expect, it } from 'vitest'
import { useMutation } from '@tanstack/react-query'

function createTestWrapper() {
  const client = new QueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return { client, wrapper }
}

function useProbeMutation() {
  const mutation = useMutation({
    mutationFn: async (_id: number) => {
      throw new Error('boom')
    },
  })
  return { mutate: mutation.mutateAsync, isError: mutation.isError, isPending: mutation.isPending }
}

it('probe immediate isError after caught mutateAsync', async () => {
  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useProbeMutation(), { wrapper })
  let caught: unknown
  await act(async () => {
    try {
      await result.current.mutate(1)
    } catch (e) {
      caught = e
    }
  })
  console.log('immediately after act:', { caught, isError: result.current.isError })
  expect(caught).toBeDefined()
})

it('probe isError after waitFor', async () => {
  const { wrapper } = createTestWrapper()
  const { result } = renderHook(() => useProbeMutation(), { wrapper })
  let caught: unknown
  await act(async () => {
    try {
      await result.current.mutate(1)
    } catch (e) {
      caught = e
    }
  })
  console.log('before extra flush:', result.current.isError)
  await act(async () => {})
  console.log('after extra flush:', result.current.isError)
  expect(caught).toBeDefined()
})
