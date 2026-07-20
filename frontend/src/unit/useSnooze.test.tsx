import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const snoozeApi = vi.hoisted(() => ({ snooze: vi.fn(), unsnooze: vi.fn() }))
vi.mock('../services/api', () => ({ snoozeApi }))

import { useSnooze, useUnsnooze } from '../hooks/useSnooze'

describe('snooze hooks', () => {
  beforeEach(() => {
    snoozeApi.snooze.mockReset()
    snoozeApi.unsnooze.mockReset()
  })

  it('snoozes and unsnoozes successfully', async () => {
    snoozeApi.snooze.mockResolvedValue(undefined)
    snoozeApi.unsnooze.mockResolvedValue(undefined)
    const snooze = renderHook(() => useSnooze())
    await act(async () => await snooze.result.current.mutate())
    expect(snooze.result.current.isError).toBe(false)
    const unsnooze = renderHook(() => useUnsnooze())
    await act(async () => await unsnooze.result.current.mutate(7))
    expect(snoozeApi.unsnooze).toHaveBeenCalledWith(7)
  })

  it('tracks and rethrows failures', async () => {
    snoozeApi.snooze.mockRejectedValueOnce(new Error('snooze failed'))
    const snooze = renderHook(() => useSnooze())
    await act(async () => await expect(snooze.result.current.mutate()).rejects.toThrow('snooze failed'))
    await waitFor(() => expect(snooze.result.current.isError).toBe(true))

    snoozeApi.unsnooze.mockRejectedValueOnce(new Error('unsnooze failed'))
    const unsnooze = renderHook(() => useUnsnooze())
    await act(async () => await expect(unsnooze.result.current.mutate(7)).rejects.toThrow('unsnooze failed'))
    await waitFor(() => expect(unsnooze.result.current.isError).toBe(true))
  })
})
