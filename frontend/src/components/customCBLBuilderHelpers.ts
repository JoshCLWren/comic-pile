import type {
  CustomCBLEntry,
  CustomCBLIssueSearchResult,
  CustomCBL,
  CustomCBLWrite,
  ReadingListEntryIntent,
  ReadingListGate,
  ReadingListMode,
  ReadingListPredecessorChange,
} from '../services/api-custom-cbl'
import { decodeCustomCBLError } from '../utils/readingListAuthoring'

const DEFAULT_GATE: ReadingListGate = 'none'

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


export interface SemanticPreviewChange {
  issueId: number
  label: string
  isNew: boolean
  moved: boolean
  oldPosition: number | null
  newPosition: number
  oldPrev: string | null
  newPrev: string | null
  oldWait: string[]
  newWait: string[]
}

export interface SemanticPreview {
  changed: SemanticPreviewChange[]
  totalChanged: number
  oldFirstUnread: string | null
  newFirstUnread: string | null
}

export function computeSemanticPreview(
  entries: CustomCBLEntry[],
  persisted: CustomCBL | null,
  dirty: boolean,
  requirements: Map<number, number[]>,
  persistedRequirements: Map<number, number[]>,
): SemanticPreview | null {
  if (!persisted || !dirty) return null
  const oldEntries = persisted.entries
  const oldIndexById = new Map(oldEntries.map((entry, index) => [entry.issue_id, index]))
  const oldFirstUnread = oldEntries.find((entry) => !entry.skipped && entry.status === 'unread')
  const newFirstUnread = entries.find((entry) => !entry.skipped && entry.status === 'unread')
  const labelFor = (issueId: number): string => {
    const entry = entries.find((candidate) => candidate.issue_id === issueId)
      ?? oldEntries.find((candidate) => candidate.issue_id === issueId)
    return entry ? `${entry.series_name} #${entry.issue_number}` : `Issue #${issueId}`
  }
  const changed = entries.flatMap((entry, index) => {
    const oldIndex = oldIndexById.get(entry.issue_id)
    const oldEntry = oldIndex !== undefined ? oldEntries[oldIndex] : undefined
    const isNew = !oldEntry
    const moved = oldIndex !== undefined && oldIndex !== index
    const waitChanged = JSON.stringify(requirements.get(entry.issue_id) ?? []) !== JSON.stringify(persistedRequirements.get(entry.issue_id) ?? [])
    const gateChanged = oldEntry ? (oldEntry.gate ?? DEFAULT_GATE) !== entry.gate || Boolean(oldEntry.skipped) !== entry.skipped : false
    if (!isNew && !moved && !waitChanged && !gateChanged) return []
    const oldPrev = oldIndex !== undefined && oldIndex > 0 ? oldEntries[oldIndex - 1] : null
    const newPrev = index > 0 ? entries[index - 1] : null
    return [{
      issueId: entry.issue_id,
      label: `${entry.series_name} #${entry.issue_number}`,
      isNew,
      moved,
      oldPosition: oldIndex !== undefined ? oldIndex + 1 : null,
      newPosition: index + 1,
      oldPrev: oldPrev ? `${oldPrev.series_name} #${oldPrev.issue_number}` : null,
      newPrev: newPrev ? `${newPrev.series_name} #${newPrev.issue_number}` : null,
      oldWait: (persistedRequirements.get(entry.issue_id) ?? []).map(labelFor),
      newWait: (requirements.get(entry.issue_id) ?? []).map(labelFor),
    }]
  })
  return {
    changed: changed.slice(0, 20),
    totalChanged: changed.length,
    oldFirstUnread: oldFirstUnread ? `${oldFirstUnread.series_name} #${oldFirstUnread.issue_number}` : null,
    newFirstUnread: newFirstUnread ? `${newFirstUnread.series_name} #${newFirstUnread.issue_number}` : null,
  }
}

export function moveEntryRelativeToEntry(
  entries: CustomCBLEntry[],
  sourceIndex: number,
  targetPosition: number,
  placement: 'before' | 'after',
): { entries: CustomCBLEntry[]; finalIndex: number } | null {
  if (!Number.isSafeInteger(targetPosition) || targetPosition < 1 || targetPosition > entries.length) return null
  if (sourceIndex < 0 || sourceIndex >= entries.length) return null
  const targetIndex = targetPosition - 1
  if (sourceIndex === targetIndex) return null
  const next = [...entries]
  const [moved] = next.splice(sourceIndex, 1)
  if (!moved) return null
  let insertAtIndex = targetIndex
  if (sourceIndex < targetIndex) insertAtIndex = targetIndex - 1
  if (placement === 'after') insertAtIndex += 1
  insertAtIndex = Math.max(0, Math.min(next.length, insertAtIndex))
  next.splice(insertAtIndex, 0, moved)
  const finalIndex = Math.max(0, Math.min(entries.length - 1, insertAtIndex))
  return { entries: normalizePositions(next), finalIndex }
}

export function findMatchedEntries(entries: CustomCBLEntry[], query: string): { entry: CustomCBLEntry; index: number }[] {
  const normalized = query.trim()
  const position = Number(normalized)
  const positionMatchEnabled = Number.isSafeInteger(position)
  return entries.flatMap((entry, index) => {
    const label = `${entry.series_name} #${entry.issue_number}`
    const matches = !normalized || (positionMatchEnabled && position === index + 1) || label.toLocaleLowerCase().includes(normalized.toLocaleLowerCase())
    return matches ? [{ entry, index }] : []
  })
}
