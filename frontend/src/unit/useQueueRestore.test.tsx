import { vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useQueueRestore } from '../pages/QueuePage/useQueueRestore'

const mutate = vi.fn()
vi.mock('../hooks/useQueue', () => ({
  useRestoreThread: vi.fn(() => ({ mutate, isPending: false, isError: false })),
}))

describe('useQueueRestore', () => {
  it('restores the series and clears any previous error', async () => {
    mutate.mockResolvedValue(undefined)
    const { result } = renderHook(() => useQueueRestore())

    await act(async () => {
      await result.current.handleRestore(7)
    })

    expect(mutate).toHaveBeenCalledWith(7)
    expect(result.current.restoreError).toBeNull()
    expect(result.current.isRestoring).toBe(false)
  })

  it('surfaces an inline error when restore fails', async () => {
    mutate.mockRejectedValueOnce(new Error('restore rejected'))
    const { result } = renderHook(() => useQueueRestore())

    await act(async () => {
      await result.current.handleRestore(7)
    })

    expect(result.current.restoreError).toBe(
      'Could not restore that series to the queue. Check your connection and try again.',
    )
  })
})
