import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useInfiniteScroll } from '../hooks/useInfiniteScroll'

describe('useInfiniteScroll', () => {
  it('returns a sentinel ref', () => {
    const { result } = renderHook(() =>
      useInfiniteScroll({
        onLoadMore: vi.fn(),
        hasMore: true,
        isLoading: false,
      }),
    )

    expect(result.current.sentinelRef).toBeDefined()
  })

  it('does not call onLoadMore when hasMore is false', () => {
    const onLoadMore = vi.fn()
    renderHook(() =>
      useInfiniteScroll({
        onLoadMore,
        hasMore: false,
        isLoading: false,
      }),
    )

    expect(onLoadMore).not.toHaveBeenCalled()
  })

  it('does not call onLoadMore when isLoading is true', () => {
    const onLoadMore = vi.fn()
    renderHook(() =>
      useInfiniteScroll({
        onLoadMore,
        hasMore: true,
        isLoading: true,
      }),
    )

    expect(onLoadMore).not.toHaveBeenCalled()
  })
})
