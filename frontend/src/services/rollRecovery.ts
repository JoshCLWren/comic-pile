/**
 * Runtime boundary for the canonical scoped Roll recovery resource.
 *
 * Rust derives the response from the same bounded Option E graph used by the
 * former aggregate, including strict/loose Reading Lists, transitive chains,
 * cycles, and depth/node limits. This module only validates and maps that wire
 * shape; it never reconstructs eligibility in the browser.
 */
import { isBoolean, isNumber, isObject, isString } from '../utils/runtimeChecks'
import type {
  RollRecoveryBlocker,
  RollRecoveryChainNode,
  RollRecoveryDiagnostic,
  RollRecoveryInfo,
  RollRecoveryPrerequisite,
} from '../types/rollState'

function positiveInteger(value: unknown): number | null {
  return isNumber(value) && Number.isSafeInteger(value) && value > 0 ? value : null
}

function integerArray(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null
  const result: number[] = []
  for (const entry of value) {
    const parsed = positiveInteger(entry)
    if (parsed == null) return null
    result.push(parsed)
  }
  return result
}

function nodeType(value: unknown): 'issue' | 'crossover' | null {
  return value === 'issue' || value === 'crossover' ? value : null
}

function satisfactionType(
  value: unknown,
): RollRecoveryBlocker['satisfaction_type'] | null {
  return value === 'item_read'
    || value === 'all_members_read'
    || value === 'checkpoint'
    || value === 'selected_members_read'
    ? value
    : null
}

function diagnosticCode(value: unknown): RollRecoveryDiagnostic['code'] | null {
  return value === 'cycle_detected'
    || value === 'depth_limit_exceeded'
    || value === 'node_limit_exceeded'
    ? value
    : null
}

function parsePrerequisite(value: unknown): RollRecoveryPrerequisite | null {
  if (!isObject(value)) return null
  const type = nodeType(value.node_type)
  const id = positiveInteger(value.node_id)
  if (type == null || id == null || !isString(value.label)) return null
  if (value.is_readable != null && !isBoolean(value.is_readable)) return null
  return {
    node_type: type,
    node_id: id,
    label: value.label,
    is_readable: value.is_readable ?? undefined,
  }
}

function parseChainNode(value: unknown): RollRecoveryChainNode | null {
  const prerequisite = parsePrerequisite(value)
  if (!prerequisite || !isObject(value) || !isBoolean(value.is_readable)) return null
  return { ...prerequisite, is_readable: value.is_readable }
}

function parseBlocker(value: unknown): RollRecoveryBlocker | null {
  if (!isObject(value)) return null
  const sourceType = nodeType(value.source_type)
  const sourceId = positiveInteger(value.source_id)
  const causingIssues = integerArray(value.causing_issue_ids)
  const causingMembers = integerArray(value.causing_member_issue_ids)
  const satisfaction = satisfactionType(value.satisfaction_type)
  if (
    sourceType == null
    || sourceId == null
    || causingIssues == null
    || causingMembers == null
    || satisfaction == null
    || !isString(value.source_label)
    || value.satisfied !== false
    || (value.note != null && !isString(value.note))
  ) return null
  const ruleId = value.rule_id == null ? null : positiveInteger(value.rule_id)
  if (value.rule_id != null && ruleId == null) return null
  return {
    rule_id: ruleId,
    source_type: sourceType,
    source_id: sourceId,
    source_label: value.source_label,
    satisfaction_type: satisfaction,
    satisfied: false,
    causing_issue_ids: causingIssues,
    causing_member_issue_ids: causingMembers,
    note: value.note ?? null,
  }
}

function parseDiagnostic(value: unknown): RollRecoveryDiagnostic | null {
  if (!isObject(value)) return null
  const type = nodeType(value.node_type)
  const id = positiveInteger(value.node_id)
  const code = diagnosticCode(value.code)
  if (type == null || id == null || code == null) return null
  const limit = value.limit == null ? undefined : positiveInteger(value.limit)
  if (value.limit != null && limit == null) return null
  return { code, node_type: type, node_id: id, limit }
}

/** Validate one scoped recovery response, failing closed on malformed data. */
export function parseRollRecovery(value: unknown): RollRecoveryInfo | null {
  if (!isObject(value)) return null
  const threadId = positiveInteger(value.original_thread_id)
  if (threadId == null || !isString(value.original_thread_title)) return null
  if (
    !Array.isArray(value.direct_blockers)
    || !Array.isArray(value.readable_prerequisites)
    || !Array.isArray(value.chains)
    || !Array.isArray(value.diagnostics)
  ) return null

  const blockers: RollRecoveryBlocker[] = []
  for (const raw of value.direct_blockers) {
    const parsed = parseBlocker(raw)
    if (!parsed) return null
    blockers.push(parsed)
  }
  const prerequisites: RollRecoveryPrerequisite[] = []
  for (const raw of value.readable_prerequisites) {
    const parsed = parsePrerequisite(raw)
    if (!parsed) return null
    prerequisites.push(parsed)
  }
  const chains: RollRecoveryChainNode[][] = []
  for (const rawChain of value.chains) {
    if (!Array.isArray(rawChain)) return null
    const chain: RollRecoveryChainNode[] = []
    for (const raw of rawChain) {
      const parsed = parseChainNode(raw)
      if (!parsed) return null
      chain.push(parsed)
    }
    chains.push(chain)
  }
  const diagnostics: RollRecoveryDiagnostic[] = []
  for (const raw of value.diagnostics) {
    const parsed = parseDiagnostic(raw)
    if (!parsed) return null
    diagnostics.push(parsed)
  }

  return {
    original_thread_id: threadId,
    original_thread_title: value.original_thread_title,
    direct_blockers: blockers,
    readable_prerequisites: prerequisites,
    chains,
    diagnostics,
  }
}
