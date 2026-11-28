import { act, renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../contexts/AuthContext'
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

/** A resolved auth value so the hook reads the signed-in reader's partition. */
function authValue(userId: number): AuthContextValue {
  const user = { id: userId, username: `reader-${userId}`, is_admin: false }
  return {
    authState: {
      status: 'authenticated',
      isLoading: false,
      user,
      error: null,
      retryCount: 0,
      lastRetryAt: null,
    },
    isAuthenticated: true,
    isLoading: false,
    user,
    login: vi.fn(async () => undefined),
    logout: vi.fn(),
    revalidateSession: vi.fn(async () => undefined),
    recoverSession: vi.fn(async () => undefined),
    retryAuth: vi.fn(async () => undefined),
    clearAuthError: vi.fn(),
  }
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

  it('keeps the pending selection on a direct read of an unrelated issue', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))
    act(() => result.current.clear(1234))
    expect(result.current.pending?.issue_id).toBe(42)
  })

  it('clears on Reset', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer(OFFER))
    act(() => result.current.clearAll())
    expect(result.current.pending).toBeNull()
  })

  it('does not leak a selection across an account switch', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AuthContext.Provider value={authValue(11)}>{children}</AuthContext.Provider>
    )
    const first = renderHook(() => useRollPendingSelection(), { wrapper })
    act(() => first.result.current.seedFromOffer(OFFER))
    expect(first.result.current.pending?.issue_id).toBe(42)
    first.unmount()

    const switched = renderHook(() => useRollPendingSelection(), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <AuthContext.Provider value={authValue(12)}>{children}</AuthContext.Provider>
      ),
    })
    expect(switched.result.current.pending).toBeNull()
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

  it('ignores an offer that does not name an exact issue and owning thread', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer({
      ...OFFER,
      thread_id: null as unknown as number,
    }))
    expect(result.current.pending).toBeNull()

    act(() => result.current.seedFromOffer({ ...OFFER, issue_id: null }))
    expect(result.current.pending).toBeNull()
  })

  it('omits optional display fields when the offer has none', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.seedFromOffer({
      thread_id: 7,
      issue_id: 43,
      issue_number: null,
      result: 0,
    }))
    expect(result.current.pending).toEqual({
      thread_id: 7,
      issue_id: 43,
      selected_at: expect.any(Number),
    })
  })

  it('persists an explicit selection through the select action', () => {
    const { result } = renderHook(() => useRollPendingSelection())
    act(() => result.current.select({
      thread_id: 8,
      issue_id: 44,
      issue_number: '44',
      result: 12,
    }))
    expect(result.current.pending).toMatchObject({
      thread_id: 8,
      issue_id: 44,
      issue_number: '44',
      result: 12,
    })
  })
})
