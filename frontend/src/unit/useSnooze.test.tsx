import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const snoozeApi = vi.hoisted(() => ({ snooze: vi.fn(), unsnooze: vi.fn() }))
const invalidateCurrentSessionAfterSnooze = vi.hoisted(() => vi.fn())
vi.mock('../services/api', () => ({ snoozeApi }))
vi.mock('../query/cacheEffects', () => ({ invalidateCurrentSessionAfterSnooze }))

import { useSnooze, useUnsnooze } from '../hooks/useSnooze'
import { queryClient } from '../query/queryClient'

describe('snooze hooks', () => {
  beforeEach(() => {
    snoozeApi.snooze.mockReset()
    snoozeApi.unsnooze.mockReset()
    invalidateCurrentSessionAfterSnooze.mockReset()
  })

  it('snoozes and narrowly invalidates the current session', async () => {
    snoozeApi.snooze.mockResolvedValue(undefined)
    invalidateCurrentSessionAfterSnooze.mockResolvedValue(undefined)
    const snooze = renderHook(() => useSnooze())

    await act(async () => await snooze.result.current.mutate())

    expect(snooze.result.current.isError).toBe(false)
    expect(snoozeApi.snooze).toHaveBeenCalledOnce()
    expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledWith(queryClient)
  })

  it('unsnoozes and narrowly invalidates the current session', async () => {
    snoozeApi.unsnooze.mockResolvedValue(undefined)
    invalidateCurrentSessionAfterSnooze.mockResolvedValue(undefined)
    const unsnooze = renderHook(() => useUnsnooze())

    await act(async () => await unsnooze.result.current.mutate(7))

    expect(unsnooze.result.current.isError).toBe(false)
    expect(snoozeApi.unsnooze).toHaveBeenCalledWith(7)
    expect(invalidateCurrentSessionAfterSnooze).toHaveBeenCalledWith(queryClient)
  })

  it('tracks and rethrows failures without invalidating cache state', async () => {
    snoozeApi.snooze.mockRejectedValueOnce(new Error('snooze failed'))
    const snooze = renderHook(() => useSnooze())
    await act(async () => await expect(snooze.result.current.mutate()).rejects.toThrow('snooze failed'))
    await waitFor(() => expect(snooze.result.current.isError).toBe(true))

    snoozeApi.unsnooze.mockRejectedValueOnce(new Error('unsnooze failed'))
    const unsnooze = renderHook(() => useUnsnooze())
    await act(async () => await expect(unsnooze.result.current.mutate(7)).rejects.toThrow('unsnooze failed'))
    await waitFor(() => expect(unsnooze.result.current.isError).toBe(true))

    expect(invalidateCurrentSessionAfterSnooze).not.toHaveBeenCalled()
  })
})
