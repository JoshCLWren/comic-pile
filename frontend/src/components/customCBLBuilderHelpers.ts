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
  if (checkpointTargets) payload.checkpoint_targets = checkpointTargets
  return payload
}

export function messageFor(error: unknown, fallback: string): string {
  const detail = decodeCustomCBLError(error)
  if (detail.message) return detail.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}
