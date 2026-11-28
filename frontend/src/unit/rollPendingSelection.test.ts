import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearAllPendingSelections,
  clearPendingSelection,
  parsePendingSelection,
  pendingSelectionStorageKey,
  readPendingSelection,
  resetRollPendingSelectionMemory,
  subscribePendingSelection,
  writePendingSelection,
} from '../services/rollPendingSelection'

const SELECTION = {
  issue_id: 42,
  thread_id: 7,
  issue_number: '42',
  result: 6,
  selected_at: 1_700_000_000_000,
}

/** Minimal in-process channel used to exercise cross-tab message parsing. */
class FakeBroadcastChannel {
  static instances: FakeBroadcastChannel[] = []
  readonly listeners = new Set<(event: MessageEvent) => void>()

  constructor(readonly name: string) {
    FakeBroadcastChannel.instances.push(this)
  }

  addEventListener(_type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.add(listener)
  }

  removeEventListener(_type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.delete(listener)
  }

  postMessage(_message: unknown): void {
    // Deliberately local: the test emits messages explicitly.
  }

  close(): void {
    this.listeners.clear()
  }

  emit(data: unknown): void {
    const event = new MessageEvent('message', { data })
    for (const listener of this.listeners) listener(event)
  }
}

describe('browser-owned roll pending selection', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    FakeBroadcastChannel.instances = []
    localStorage.clear()
    resetRollPendingSelectionMemory()
  })

  it('restores the same exact issue after a reload', () => {
    writePendingSelection(11, SELECTION)
    // A reload is a fresh module cache but the same browser storage.
    resetRollPendingSelectionMemory()
    expect(readPendingSelection(11)).toEqual(SELECTION)
  })

  it('notifies a second tab through the storage event', () => {
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(11, listener)
    try {
      writePendingSelection(11, SELECTION)
      // A different tab writes the same key; this tab only sees a storage event.
      localStorage.setItem(pendingSelectionStorageKey(11), JSON.stringify(SELECTION))
      window.dispatchEvent(new StorageEvent('storage', {
        key: pendingSelectionStorageKey(11),
        newValue: JSON.stringify(SELECTION),
      }))
      expect(listener).toHaveBeenCalled()
      expect(readPendingSelection(11)).toEqual(SELECTION)
    } finally {
      unsubscribe()
    }
  })

  it('keeps the selection after a failed rate (no clear is issued)', () => {
    writePendingSelection(11, SELECTION)
    // A failed request never calls clear(issueId); the selection survives.
    expect(readPendingSelection(11)).toEqual(SELECTION)
  })

  it('clears only on a successful rate of that exact issue', () => {
    writePendingSelection(11, SELECTION)
    clearPendingSelection(11, 999)
    expect(readPendingSelection(11)).toEqual(SELECTION)
    clearPendingSelection(11, SELECTION.issue_id)
    expect(readPendingSelection(11)).toBeNull()
  })

  it('keeps the selection on a direct read of an unrelated issue', () => {
    writePendingSelection(11, SELECTION)
    clearPendingSelection(11, 100)
    expect(readPendingSelection(11)).toEqual(SELECTION)
  })

  it('clears the selection on Reset', () => {
    writePendingSelection(11, SELECTION)
    clearAllPendingSelections(11)
    expect(readPendingSelection(11)).toBeNull()
  })

  it('does not leak a selection across an account switch', () => {
    writePendingSelection(11, SELECTION)
    expect(readPendingSelection(12)).toBeNull()
    writePendingSelection(12, { ...SELECTION, issue_id: 9, thread_id: 3 })
    expect(readPendingSelection(11)).toEqual(SELECTION)
    expect(readPendingSelection(12)?.issue_id).toBe(9)
  })

  it('rejects malformed or foreign storage records', () => {
    localStorage.setItem(pendingSelectionStorageKey(11), '{not json')
    expect(readPendingSelection(11)).toBeNull()
    expect(parsePendingSelection(null)).toBeNull()
    expect(parsePendingSelection('null')).toBeNull()
    expect(parsePendingSelection('[]')).toBeNull()
    expect(parsePendingSelection('"issue"')).toBeNull()
    expect(parsePendingSelection(JSON.stringify({ issue_id: -1, thread_id: 7 }))).toBeNull()
    expect(parsePendingSelection(JSON.stringify({ issue_id: 1.5, thread_id: 7 }))).toBeNull()
    expect(parsePendingSelection(JSON.stringify({ issue_id: 42, thread_id: 0 }))).toBeNull()
    expect(parsePendingSelection(JSON.stringify({ issue_id: 42 }))).toBeNull()
  })

  it('parses optional fields only when their wire shape is valid', () => {
    const parsed = parsePendingSelection(JSON.stringify({
      issue_id: 42,
      thread_id: 7,
      issue_number: 12,
      result: 'six',
      selected_at: -5,
    }))
    expect(parsed?.issue_id).toBe(42)
    expect(parsed?.thread_id).toBe(7)
    expect(parsed?.issue_number).toBeUndefined()
    expect(parsed?.result).toBeUndefined()
    // A bad timestamp falls back to the client clock, never a fabricated id.
    expect(parsed?.selected_at).toBeGreaterThan(0)

    const withOptional = parsePendingSelection(JSON.stringify({
      issue_id: 42,
      thread_id: 7,
      issue_number: '42',
      result: 5.5,
      selected_at: 1_700_000_000_000,
    }))
    expect(withOptional).toEqual({
      issue_id: 42,
      thread_id: 7,
      issue_number: '42',
      result: 5.5,
      selected_at: 1_700_000_000_000,
    })
  })

  it('parses cross-tab BroadcastChannel messages and ignores foreign keys', () => {
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel)
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(11, listener)
    const channel = FakeBroadcastChannel.instances.at(-1)
    if (!channel) throw new Error('BroadcastChannel subscription was not created')

    channel.emit({ key: pendingSelectionStorageKey(12), selection: SELECTION })
    expect(readPendingSelection(11)).toBeNull()

    channel.emit({ key: pendingSelectionStorageKey(11), selection: SELECTION })
    expect(readPendingSelection(11)).toEqual(SELECTION)

    channel.emit({ key: pendingSelectionStorageKey(11), selection: { issue_id: 'not-an-id' } })
    expect(readPendingSelection(11)).toBeNull()

    channel.emit({ key: pendingSelectionStorageKey(11), selection: null })
    expect(readPendingSelection(11)).toBeNull()
    expect(listener).toHaveBeenCalled()
    unsubscribe()
  })

  it('keeps an in-memory selection when browser storage is unavailable', () => {
    const blocked = () => { throw new Error('storage blocked') }
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(blocked)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(blocked)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(blocked)

    expect(readPendingSelection(21)).toBeNull()
    writePendingSelection(21, SELECTION)
    expect(readPendingSelection(21)).toEqual(SELECTION)
    clearPendingSelection(21, SELECTION.issue_id)
    expect(readPendingSelection(21)).toBeNull()
  })

  it('still mirrors a selection through storage when BroadcastChannel is unavailable', () => {
    vi.stubGlobal('BroadcastChannel', class {
      constructor() { throw new Error('channel blocked') }
    })
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(11, listener)
    writePendingSelection(11, SELECTION)
    expect(listener).toHaveBeenCalled()
    unsubscribe()
  })

  it('survives a window that cannot register storage listeners', () => {
    vi.spyOn(window, 'addEventListener').mockImplementation(() => {
      throw new Error('listener blocked')
    })
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(31, listener)
    expect(listener).not.toHaveBeenCalled()
    unsubscribe()
  })

  it('mirrors a selection in-process when BroadcastChannel is not defined', () => {
    vi.stubGlobal('BroadcastChannel', undefined)
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(51, listener)
    writePendingSelection(51, SELECTION)
    expect(listener).toHaveBeenCalled()
    expect(readPendingSelection(51)).toEqual(SELECTION)
    unsubscribe()
  })

  it('uses the client clock when a persisted selection has no usable timestamp', () => {
    writePendingSelection(52, { ...SELECTION, selected_at: 0 })
    expect(readPendingSelection(52)?.selected_at).toBeGreaterThan(0)
  })

  it('ignores storage events for other keys but applies a remote clear', () => {
    const listener = vi.fn()
    const unsubscribe = subscribePendingSelection(53, listener)
    writePendingSelection(53, SELECTION)

    window.dispatchEvent(new StorageEvent('storage', {
      key: 'comic-pile:some:other:key',
      newValue: JSON.stringify({ ...SELECTION, issue_id: 999 }),
    }))
    expect(readPendingSelection(53)?.issue_id).toBe(42)

    window.dispatchEvent(new StorageEvent('storage', {
      key: pendingSelectionStorageKey(53),
      newValue: null,
    }))
    expect(readPendingSelection(53)).toBeNull()
    expect(listener).toHaveBeenCalled()
    unsubscribe()
  })

  it('subscribes when the window has no addEventListener function', () => {
    const original = window.addEventListener
    Object.defineProperty(window, 'addEventListener', { configurable: true, value: undefined })
    try {
      const listener = vi.fn()
      const unsubscribe = subscribePendingSelection(54, listener)
      writePendingSelection(54, SELECTION)
      expect(listener).toHaveBeenCalledTimes(1)
      unsubscribe()
    } finally {
      Object.defineProperty(window, 'addEventListener', { configurable: true, value: original })
    }
  })

  it('does not clear an empty selection for an issue-scoped clear', () => {
    expect(readPendingSelection(55)).toBeNull()
    clearPendingSelection(55, SELECTION.issue_id)
    expect(readPendingSelection(55)).toBeNull()
  })

  it('partitions anonymous and empty users away from signed-in readers', () => {
    expect(pendingSelectionStorageKey(null)).toBe(pendingSelectionStorageKey(''))
    expect(pendingSelectionStorageKey(undefined)).toBe(pendingSelectionStorageKey(null))
    expect(pendingSelectionStorageKey(null)).not.toBe(pendingSelectionStorageKey(11))
    expect(pendingSelectionStorageKey('reader/a')).toContain('reader%2Fa')
  })
})
