import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRollPendingSelection } from '../hooks/useRollPendingSelection'
import {
  parsePendingSelection,
  pendingSelectionStorageKey,
  resetRollPendingSelectionMemory,
} from '../services/rollPendingSelection'

const OFFER = {
  thread_id: 7,
  issue_id: 42,
  issue_number: '42',
  result: 6,
}

describe('useRollPendingSelection', () => {
  beforeEach(() => {
    localStorage.clear()
    resetRollPendingSelectionMemory()
  })

  it('restores the same pending issue after a reload', () => {
    const first = renderHook(() => useRollPendingSelection())
    act(() => first.result.current.seedFromOffer(OFFER))
    first.unmount()

    // A remount simulates reload: the hook reads the same browser storage.
    resetRollPendingSelectionMemory()
    const restored = renderHook(() => useRollPendingSelection())
    expect(restored.result.current.pending).toEqual(parsePendingSelection(
      localStorage.getItem(pendingSelectionStorageKey(null)),
    ))
    expect(restored.result.current.pending?.issue_id).toBe(42)
  })

  it('sees another tab write through a storage event', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => {
      localStorage.setItem(
        pendingSelectionStorageKey(null),
        JSON.stringify({ ...OFFER, selected_at: 1 }),
      )
      window.dispatchEvent(new StorageEvent('storage', {
        key: pendingSelectionStorageKey(null),
        newValue: JSON.stringify({ ...OFFER, selected_at: 1 }),
      }))
    })
    expect(result.current.pending?.issue_id).toBe(42)
  })

  it('keeps the selection on a failed rate and clears it only on a successful matching rate', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))

    // A failed request never calls clear; an unrelated issue cannot clear it.
    act(() => result.current.clear(999))
    expect(result.current.pending?.issue_id).toBe(42)

    act(() => result.current.clear(42))
    expect(result.current.pending).toBeNull()
  })

  it('clears on Reset and keeps an unrelated direct read', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))
    act(() => result.current.clear(1234))
    expect(result.current.pending?.issue_id).toBe(42)
    act(() => result.current.clearAll())
    expect(result.current.pending).toBeNull()
  })

  it('seeds the exact issue from an offer response', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))
    expect(result.current.pending).toMatchObject({
      issue_id: 42,
      thread_id: 7,
      result: 6,
    })
  })

  it('replaces an exact selection when a legacy offer has no issue row', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))
    expect(result.current.pending?.issue_id).toBe(42)

    act(() => result.current.seedFromOffer({ ...OFFER, issue_id: null }))
    expect(result.current.pending).toBeNull()
  })

  it('does not issue a server call to cancel; it only clears local state', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'))
    try {
      const { result } = renderHook(() => useRollPendingSelection())
      act(() => result.current.seedFromOffer(OFFER))
      act(() => result.current.clear())
      expect(result.current.pending).toBeNull()
      expect(fetchSpy).not.toHaveBeenCalled()
    } finally {
      fetchSpy.mockRestore()
    }
  })
})
