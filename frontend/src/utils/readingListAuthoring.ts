import axios from 'axios'

import type {
  ReadingListCycleEdge,
  ReadingListGate,
  ReadingListMode,
  ReadingListPredecessorChange,
} from '../services/api-custom-cbl'
import {
  isNumber,
  isObject,
  isString,
  type JsonValue,
} from './runtimeChecks'

/** One editable entry projection used for local gate previews. */
export interface ReadingListIntentEntry {
  issue_id: number
  gate: ReadingListGate
  skipped: boolean
}

/** Decoded structured error detail returned by Reading List authoring writes. */
export interface CustomCBLErrorDetail {
  code: string | null
  message: string | null
  predecessorChanges: ReadingListPredecessorChange[]
  cyclePath: ReadingListCycleEdge[]
}

const EMPTY_ERROR_DETAIL: CustomCBLErrorDetail = {
  code: null,
  message: null,
  predecessorChanges: [],
  cyclePath: [],
}

function decodeNumberArray(value: JsonValue | undefined): number[] {
  if (!Array.isArray(value)) return []
  const result: number[] = []
  for (const item of value) {
    if (isNumber(item)) result.push(Number(item))
  }
  return result
}

function decodeStringArray(value: JsonValue | undefined): string[] {
  if (!Array.isArray(value)) return []
  const result: string[] = []
  for (const item of value) {
    if (isString(item)) result.push(item)
  }
  return result
}

function decodeNamedArray<T>(
  value: JsonValue | undefined,
  decode: (item: JsonValue) => T | null,
): T[] {
  if (!Array.isArray(value)) return []
  const result: T[] = []
  for (const item of value) {
    const decoded = decode(item)
    if (decoded !== null) result.push(decoded)
  }
  return result
}

function decodePredecessorChange(value: JsonValue): ReadingListPredecessorChange | null {
  if (!isObject(value)) return null
  const issueId = value.issue_id
  const issueName = value.issue_name
  if (!isNumber(issueId) || !isString(issueName)) return null
  return {
    issue_id: Number(issueId),
    issue_name: issueName,
    before_issue_ids: decodeNumberArray(value.before_issue_ids),
    before_issue_names: decodeStringArray(value.before_issue_names),
    after_issue_ids: decodeNumberArray(value.after_issue_ids),
    after_issue_names: decodeStringArray(value.after_issue_names),
  }
}

function decodeCycleEdge(value: JsonValue): ReadingListCycleEdge | null {
  if (!isObject(value)) return null
  const sourceId = value.source_issue_id
  const targetId = value.target_issue_id
  if (!isNumber(sourceId) || !isNumber(targetId)) return null
  const origin = isString(value.origin) ? value.origin : null
  const prerequisite = value.prerequisite_origin
  const prerequisiteOrigin =
    prerequisite === 'reader' || prerequisite === 'converted' ? prerequisite : null
  const edge: ReadingListCycleEdge = {
    source_issue_id: Number(sourceId),
    target_issue_id: Number(targetId),
    origin,
    prerequisite_origin: prerequisiteOrigin,
    provenance: decodeStringArray(value.provenance),
  }
  if (isString(value.source_issue_name)) edge.source_issue_name = value.source_issue_name
  if (isString(value.target_issue_name)) edge.target_issue_name = value.target_issue_name
  if (isNumber(value.source_thread_id) && Number.isSafeInteger(value.source_thread_id) && value.source_thread_id > 0) edge.source_thread_id = value.source_thread_id
  if (isNumber(value.target_thread_id) && Number.isSafeInteger(value.target_thread_id) && value.target_thread_id > 0) edge.target_thread_id = value.target_thread_id
  return edge
}

/**
 * Decode the structured `detail` object of a failed Reading List authoring write.
 *
 * @param error - Rejected value from the custom CBL API, usually an AxiosError.
 * @returns Decoded detail, or an empty detail when the shape is unrecognized.
 */
export function decodeCustomCBLError(error: unknown): CustomCBLErrorDetail {
  if (!axios.isAxiosError(error)) return EMPTY_ERROR_DETAIL
  const detail = error.response?.data?.detail
  if (isString(detail)) return { ...EMPTY_ERROR_DETAIL, message: detail }
  if (!isObject(detail)) return EMPTY_ERROR_DETAIL
  return {
    code: isString(detail.code) ? detail.code : null,
    message: isString(detail.message) ? detail.message : null,
    predecessorChanges: decodeNamedArray(detail.predecessor_changes, decodePredecessorChange),
    cyclePath: decodeNamedArray(detail.path, decodeCycleEdge),
  }
}

/** Join stored predecessor names into a readable phrase. */
export function describePredecessors(names: readonly string[]): string {
  if (names.length === 0) return 'nothing'
  if (names.length === 1) return names[0] ?? 'nothing'
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  const head = names.slice(0, -1).join(', ')
  return `${head}, and ${names[names.length - 1]}`
}

/**
 * Describe one stored predecessor change in reader-facing "was / now" terms.
 *
 * @param change - Named before/after requirement pair from the server.
 * @returns Sentence naming the changed Issue and its old and new requirements.
 */
export function describePredecessorChange(change: ReadingListPredecessorChange): string {
  const before = describePredecessors(change.before_issue_names)
  const after = describePredecessors(change.after_issue_names)
  const wasWaiting = change.before_issue_names.length > 0
  const isWaiting = change.after_issue_names.length > 0
  if (!wasWaiting && isWaiting) {
    return `${change.issue_name} now waits on ${after}.`
  }
  if (wasWaiting && !isWaiting) {
    return `${change.issue_name} no longer waits on anything (was waiting on ${before}).`
  }
  return `${change.issue_name} was waiting on ${before}, now waits on ${after}.`
}

/**
 * Describe a rejected cycle path as a named chain.
 *
 * Prefers the canonical Issue names returned with the 422 so nodes outside the
 * edited list (other lists, series order, prerequisites) are identifiable. Falls
 * back to the caller's resolver for older responses that omit names.
 *
 * @param edges - Structured cycle edges returned with the 422.
 * @param nameFor - Resolves a persisted Issue ID to its display name.
 * @param context - Create reports a pre-existing cycle; save reports a rejected order.
 * @returns Actionable sentence readers can act on.
 */
export function describeCyclePath(
  edges: ReadingListCycleEdge[],
  nameFor: (issueId: number) => string,
  context: 'create' | 'save' = 'save',
): string {
  const prefix = context === 'create'
    ? 'An existing reading cycle prevents creating this list'
    : 'This order would create a reading cycle'
  const remediation = context === 'create'
    ? 'Review the affected reading requirements, then try again. No new list was saved.'
    : 'Change the sequence and try again.'
  const first = edges[0]
  if (!first) {
    return `${prefix}. ${remediation}`
  }
  const resolve = (issueId: number, provided?: string) => provided ?? nameFor(issueId)
  const nodes = [resolve(first.source_issue_id, first.source_issue_name)]
  for (const edge of edges) nodes.push(resolve(edge.target_issue_id, edge.target_issue_name))
  return `${prefix}: ${nodes.join(' → ')}. ${remediation}`
}

/**
 * Mirror the server's stored positional requirements for editor previews.
 *
 * Skipped entries never contribute or receive requirements; a `hold` milestone
 * blocks every later entry until the milestone and all earlier entries are read.
 *
 * @param mode - Current strict/loose mode of the edited list.
 * @param entries - Editable entries in display order, including skipped ones.
 * @returns Issue ID to the Issue IDs it waits on, in display order.
 */
export function computeEntryRequirements(
  mode: ReadingListMode,
  entries: readonly ReadingListIntentEntry[],
): Map<number, number[]> {
  const result = new Map<number, number[]>()
  const earlier: number[] = []
  let hold: number[] = []
  for (const entry of entries) {
    if (entry.skipped) continue
    const sources = new Set(hold)
    if (mode === 'strict' || entry.gate === 'hold') {
      for (const issueId of earlier) sources.add(issueId)
    }
    if (entry.gate === 'after_previous') {
      const previous = earlier[earlier.length - 1]
      if (previous !== undefined) sources.add(previous)
    }
    result.set(entry.issue_id, earlier.filter((issueId) => sources.has(issueId)))
    earlier.push(entry.issue_id)
    if (entry.gate === 'hold') hold = earlier.slice()
  }
  return result
}
