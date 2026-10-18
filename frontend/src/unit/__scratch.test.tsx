import { renderHook, waitFor } from '@testing-library/react'
import { it, vi, beforeEach } from 'vitest'
import { useQuery } from '@tanstack/react-query'
import { queryClient } from '../query/queryClient'
beforeEach(() => { queryClient.clear(); vi.clearAllMocks() })

it('useQuery with initialData still calls queryFn', async () => {
  const fn = vi.fn().mockResolvedValue({ ok: true })
  const { result } = renderHook(() =>
    useQuery({ queryKey: ['scratch2'], queryFn: fn, enabled: true, initialData: { ok: false } }),
  )
  await waitFor(() => expect(fn).toHaveBeenCalled())
  console.log('INITIALDATA CALLS:', fn.mock.calls.length, 'DATA:', JSON.stringify(result.current.data))
})
