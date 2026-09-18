import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  resetSessionGreetingMemory,
  SESSION_STARTED_TOAST_MESSAGE,
  SESSION_STORAGE_KEY_PREFIX,
  trackSessionGreeting,
} from '../utils/sessionGreeting'

function storageKey(userId: number | 'anonymous'): string {
  return `${SESSION_STORAGE_KEY_PREFIX}_${userId}`
}

function createStorage(initial: Record<string, string> = {}) {
  const store = new Map<string, string>(Object.entries(initial))
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key)
    }),
    clear: vi.fn(() => {
      store.clear()
    }),
  }
}

describe('trackSessionGreeting', () => {
  beforeEach(() => {
    localStorage.clear()
    resetSessionGreetingMemory()
  })

  afterEach(() => {
    resetSessionGreetingMemory()
    localStorage.clear()
  })

  it('writes the session id without toasting on a first session', () => {
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 5, userId: 3, showToast })
    expect(localStorage.getItem(storageKey(3))).toBe('5')
    expect(showToast).not.toHaveBeenCalled()
  })

  it('does not toast when the stored session matches the current session', () => {
    localStorage.setItem(storageKey(3), '5')
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 5, userId: 3, showToast })
    expect(showToast).not.toHaveBeenCalled()
    expect(localStorage.getItem(storageKey(3))).toBe('5')
  })

  it('toasts once and persists when a genuinely new session starts', () => {
    localStorage.setItem(storageKey(3), '5')
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
    expect(showToast).toHaveBeenCalledTimes(1)
    expect(showToast).toHaveBeenCalledWith(SESSION_STARTED_TOAST_MESSAGE, 'info')
    expect(localStorage.getItem(storageKey(3))).toBe('9')
  })

  it('does not re-toast the same new session across consumers', () => {
    localStorage.setItem(storageKey(3), '5')
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
    trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
    expect(showToast).toHaveBeenCalledTimes(1)
  })

  it('uses an anonymous storage key when no user id is present', () => {
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 7, showToast })
    expect(localStorage.getItem(storageKey('anonymous'))).toBe('7')
  })

  it('ignores a malformed stored session id and replaces it with the current id', () => {
    localStorage.setItem(storageKey(3), 'not-a-number')
    const showToast = vi.fn()
    trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
    expect(showToast).not.toHaveBeenCalled()
    expect(localStorage.getItem(storageKey(3))).toBe('9')
  })

  it('does nothing when the observed session id is missing', () => {
    const showToast = vi.fn()
    // SAFETY: a malformed current-session response can carry a missing id at runtime even though the API type declares it required.
    // Cast to any to bypass the type checker for this edge case test.
    trackSessionGreeting({ sessionId: null as any, userId: 3, showToast })
    expect(showToast).not.toHaveBeenCalled()
    expect(localStorage.getItem(storageKey(3))).toBeNull()
  })

  it('still succeeds when reading the stored session id fails', () => {
    const originalStorage = window.localStorage
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: vi.fn(() => {
          throw new Error('storage unavailable')
        }),
        setItem: vi.fn(),
        removeItem: vi.fn(),
        clear: vi.fn(),
      },
    })
    try {
      const showToast = vi.fn()
      trackSessionGreeting({ sessionId: 5, userId: 3, showToast })
      expect(showToast).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
  })

  it('still reports a new session when persisting fails, without crashing', () => {
    const originalStorage = window.localStorage
    const storage = createStorage({ [storageKey(3)]: '5' })
    storage.setItem.mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: storage,
    })
    try {
      const showToast = vi.fn()
      trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
      expect(showToast).toHaveBeenCalledTimes(1)
      trackSessionGreeting({ sessionId: 9, userId: 3, showToast })
      expect(showToast).toHaveBeenCalledTimes(1)
    } finally {
      Object.defineProperty(window, 'localStorage', {
        configurable: true,
        value: originalStorage,
      })
    }
  })
})