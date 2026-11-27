import { beforeEach, describe, expect, it } from 'vitest'
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

describe('browser-owned roll pending selection', () => {
  beforeEach(() => {
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
    expect(parsePendingSelection(JSON.stringify({ issue_id: -1, thread_id: 7 }))).toBeNull()
    expect(parsePendingSelection(JSON.stringify({ issue_id: 1.5, thread_id: 7 }))).toBeNull()
  })
})
