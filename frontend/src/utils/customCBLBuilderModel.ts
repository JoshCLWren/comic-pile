import type {
  CustomCBLEntry,
  CustomCBLIssueSearchResult,
  ReadingListGate,
  ReadingListMode,
} from '../services/api-custom-cbl'

export const DEFAULT_MODE: ReadingListMode = 'loose'
export const DEFAULT_GATE: ReadingListGate = 'none'
export const ENTRY_PAGE_SIZE = 30

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

export function checkpointTargetsFor(
  entries: readonly CustomCBLEntry[],
): Record<number, number[]> | null {
  const targets: Record<number, number[]> = {}
  for (const entry of entries) {
    const values = entry.checkpoint_target_issue_ids
    if (entry.is_checkpoint && values && values.length > 0) {
      targets[entry.issue_id] = [...values]
    }
  }
  return Object.keys(targets).length > 0 ? targets : null
}
