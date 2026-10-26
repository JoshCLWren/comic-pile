import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { invalidateAfterQueueMutation } from '../query/cacheEffects'
import { usePotentialDuplicates } from '../hooks/usePotentialDuplicates'
import type { CheckPotentialDuplicatesRequest } from '../types'
const { check } = vi.hoisted(() => ({ check: vi.fn() }))
vi.mock('../services/api-threads', () => ({ threadsApi: { checkPotentialDuplicates: check } }))
function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Provider({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}
describe('advisory duplicate queries', () => {
  it('clears loading immediately when an in-flight title is cleared', async () => {
    let finish: ((value: { matches: [] }) => void) | undefined
    check.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { result, rerender } = renderHook(({ title }) => usePotentialDuplicates({ title, format: 'Comic' }, true), { initialProps: { title: 'Saga' }, wrapper: createWrapper() })
    await waitFor(() => expect(result.current.isChecking).toBe(true))
    rerender({ title: '' })
    expect(result.current).toEqual({ matches: [], isChecking: false })
    await act(async () => { finish?.({ matches: [] }) })
    expect(result.current).toEqual({ matches: [], isChecking: false })
  })
  it('does not request duplicates while its form is closed', () => {
    check.mockClear()
    const { result } = renderHook(() => usePotentialDuplicates({ title: 'Saga', format: 'Comic' }, false), { wrapper: createWrapper() })
    expect(result.current.isChecking).toBe(false)
    expect(check).not.toHaveBeenCalled()
  })
  it('keeps create and edit queries separate and normalizes their input', async () => {
    check.mockReset().mockResolvedValue({ matches: [] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const provider = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    renderHook(() => {
      usePotentialDuplicates({ title: ' Saga ', format: ' Comic ' }, true)
      usePotentialDuplicates({ title: 'Saga', format: 'Comic', exclude_thread_id: 7 }, true)
    }, { wrapper: provider })
    await waitFor(() => expect(check).toHaveBeenCalledTimes(2))
    const inputs: CheckPotentialDuplicatesRequest[] = check.mock.calls.map(([input]) => input)
    expect(inputs).toEqual(expect.arrayContaining([{ title: 'Saga', format: 'Comic' }, { title: 'Saga', format: 'Comic', exclude_thread_id: 7 }]))
  })
  it('refreshes a cached empty answer after a library mutation', async () => {
    check.mockReset().mockResolvedValueOnce({ matches: [] })
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
    const provider = ({ children }: PropsWithChildren) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result } = renderHook(() => usePotentialDuplicates({ title: 'Saga', format: 'Comic' }, true), { wrapper: provider })
    await waitFor(() => expect(check).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(result.current.isChecking).toBe(false))
    const matches = [{ id: 9, title: 'Saga', match_type: 'fuzzy' }]
    check.mockResolvedValue({ matches })
    await act(async () => { await invalidateAfterQueueMutation(client) })
    await waitFor(() => expect(result.current.matches).toEqual(matches))
    expect(check).toHaveBeenCalledTimes(2)
  })

})
