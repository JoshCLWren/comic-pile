import type {
  CustomCBLEntry,
  CustomCBLIssueSearchResult,
  CustomCBLWrite,
  ReadingListEntryIntent,
  ReadingListGate,
  ReadingListMode,
  ReadingListPredecessorChange,
} from '../services/api-custom-cbl'
import { decodeCustomCBLError } from '../utils/readingListAuthoring'

const DEFAULT_GATE: ReadingListGate = 'none'

export interface ReadingListUndoSnapshot {
  payload: CustomCBLWrite
  baseline: string
}

function undoStorageKey(userId: number, listId: number): string {
  return `comic-pile:reading-list-undo:${userId}:${listId}`
}

function isUndoSnapshot(value: unknown, updatedAt: string): value is ReadingListUndoSnapshot {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Partial<ReadingListUndoSnapshot>
  return (
    candidate.baseline === updatedAt &&
    typeof candidate.payload === 'object' &&
    candidate.payload !== null &&
    Array.isArray(candidate.payload.issue_ids)
  )
}

/** Restore only the Undo snapshot for this owner, list, and exact saved version. */
export function restoreReadingListUndo(
  userId: number,
  listId: number,
  updatedAt: string,
): ReadingListUndoSnapshot | null {
  try {
    const key = undoStorageKey(userId, listId)
    const stored = window.sessionStorage.getItem(key)
    if (!stored) return null
    const parsed: unknown = JSON.parse(stored)
    if (isUndoSnapshot(parsed, updatedAt)) return parsed
    window.sessionStorage.removeItem(key)
    return null
  } catch {
    // Storage can be unavailable or contain invalid JSON; the saved list is
    // still editable and a future save can create a fresh in-memory Undo.
    return null
  }
}

/** Persist one list-scoped Undo across reloads without storing reads or ratings. */
export function writeReadingListUndo(
  userId: number,
  listId: number,
  snapshot: ReadingListUndoSnapshot | null,
): void {
  try {
    const key = undoStorageKey(userId, listId)
    if (snapshot) window.sessionStorage.setItem(key, JSON.stringify(snapshot))
    else window.sessionStorage.removeItem(key)
  } catch {
    // The in-memory Undo remains available when browser storage is restricted.
  }
}

export function normalizePositions(entries: CustomCBLEntry[]): CustomCBLEntry[] {
  return entries.map((entry, position) => ({
    ...entry,
    position,
    is_checkpoint: Boolean(entry.is_checkpoint),
    skipped: Boolean(entry.skipped),
    gate: entry.gate ?? DEFAULT_GATE,
  }))
}

export function draftEntry(result: CustomCBLIssueSearchResult, position: number): CustomCBLEntry {
  return {
    id: -result.issue_id,
    position,
    issue_id: result.issue_id,
    thread_id: result.thread_id,
    series_name: result.series_name,
    issue_number: result.issue_number,
    status: result.status,
    is_checkpoint: false,
    gate: DEFAULT_GATE,
    skipped: false,
  }
}

export function sameEntries(left: CustomCBLEntry[], right: CustomCBLEntry[]): boolean {
  return (
    left.length === right.length &&
    left.every((entry, index) => {
      const other = right[index]
      return (
        other !== undefined &&
        entry.issue_id === other.issue_id &&
        entry.gate === (other.gate ?? DEFAULT_GATE) &&
        entry.skipped === (other.skipped ?? false) &&
        Boolean(entry.is_checkpoint) === Boolean(other.is_checkpoint)
      )
    })
  )
}

export function checkpointTargetsFor(entries: readonly CustomCBLEntry[]): Record<number, number[]> | null {
  const targets: Record<number, number[]> = {}
  for (const entry of entries) {
    const values = entry.checkpoint_target_issue_ids
    if (entry.is_checkpoint && values && values.length > 0) {
      targets[entry.issue_id] = [...values]
    }
  }
  return Object.keys(targets).length > 0 ? targets : null
}

export function buildWritePayload(
  name: string,
  description: string,
  mode: ReadingListMode,
  entries: CustomCBLEntry[],
  confirmed: ReadingListPredecessorChange[] | null,
  checkpointTargets: Record<number, number[]> | null = null,
  expectedUpdatedAt: string | null = null,
): CustomCBLWrite {
  const issueIds: number[] = []
  const checkpointIds: number[] = []
  const entryIntents: Record<number, ReadingListEntryIntent> = {}
  for (const entry of entries) {
    issueIds.push(entry.issue_id)
    if (entry.is_checkpoint) checkpointIds.push(entry.issue_id)
    entryIntents[entry.issue_id] = { gate: entry.gate, skipped: entry.skipped }
  }
  const payload: CustomCBLWrite = {
    name: name.trim(),
    description: description.trim() || null,
    mode,
    issue_ids: issueIds,
    entry_intents: entryIntents,
    checkpoint_issue_ids: checkpointIds,
  }
  if (confirmed) payload.confirmed_predecessor_changes = confirmed
  const targets = checkpointTargets ?? checkpointTargetsFor(entries)
  if (targets) payload.checkpoint_targets = targets
  if (expectedUpdatedAt) payload.expected_updated_at = expectedUpdatedAt
  return payload
}

export function messageFor(error: unknown, fallback: string): string {
  const detail = decodeCustomCBLError(error)
  if (detail.message) return detail.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}
