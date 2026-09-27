import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDebounce } from '../hooks/useDebounce'

describe('useDebounce', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('publishes the value that stayed unchanged for the full delay', () => {
    const { result, rerender } = renderHook(({ value }) => useDebounce(value, 300), {
      initialProps: { value: 'a' },
    })

    expect(result.current).toBe('a')

    rerender({ value: 'b' })
    expect(result.current).toBe('a')

    act(() => {
      vi.advanceTimersByTime(299)
    })
    expect(result.current).toBe('a')

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(result.current).toBe('b')
  })

  it('only settles the most recent value when changes arrive faster than the delay', () => {
    const { result, rerender } = renderHook(({ value }) => useDebounce(value, 300), {
      initialProps: { value: '' },
    })

    for (const value of ['v', 'va', 'vau', 'vaughan']) {
      rerender({ value })
      act(() => {
        vi.advanceTimersByTime(100)
      })
    }

    expect(result.current).toBe('')

    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(result.current).toBe('vaughan')
  })

  it('cancels the pending publish when the hook unmounts', () => {
    const { rerender, unmount } = renderHook(({ value }) => useDebounce(value, 300), {
      initialProps: { value: 'a' },
    })

    rerender({ value: 'b' })
    unmount()

    expect(() =>
      act(() => {
        vi.advanceTimersByTime(600)
      }),
    ).not.toThrow()
    expect(vi.getTimerCount()).toBe(0)
  })
})
