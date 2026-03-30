import type { Dependency, Thread } from '../types'

export type GateStatus = 'blocked' | 'satisfied' | 'dormant'

export interface TimelineGateEntry {
  targetIssueId: number
  issueNumberText: string | null
  issueNumberValue: number | null
  targetLabel: string
  prerequisiteLabels: string[]
  status: GateStatus
  isCurrent: boolean
}

export interface TimelineSpanEntry {
  id: string
  startNumber: number | null
  endNumber: number | null
  isOpenEnded: boolean
  label: string
  isCurrent: boolean
}

export type TimelineEntry =
  | { kind: 'gate'; gate: TimelineGateEntry }
  | { kind: 'span'; span: TimelineSpanEntry }

interface BuildTimelineParams {
  thread: Thread
  dependencies: Dependency[]
}

export function extractIssueNumber(label?: string | null): string | null {
  if (!label) {
    return null
  }
  const hashIndex = label.lastIndexOf('#')
  if (hashIndex === -1) {
    return null
  }
  const value = label.slice(hashIndex + 1).trim()
  return value || null
}

export function issueStringToNumber(issueNumber: string | null | undefined): number | null {
  if (!issueNumber) {
    return null
  }
  const normalized = issueNumber.replace(/[^\d.]/g, '')
  if (!normalized) {
    return null
  }
  const parsed = Number.parseFloat(normalized)
  return Number.isNaN(parsed) ? null : parsed
}

function determineOrderValue(issueValue: number | null, fallbackId: number | null): number | null {
  if (issueValue !== null) {
    return issueValue
  }
  if (fallbackId !== null) {
    return fallbackId
  }
  return null
}

function compareOrder(a: number | null, b: number | null, aLabel: string, bLabel: string): number {
  if (a === null && b === null) {
    return aLabel.localeCompare(bLabel)
  }
  if (a === null) {
    return 1
  }
  if (b === null) {
    return -1
  }
  if (a === b) {
    return aLabel.localeCompare(bLabel)
  }
  return a - b
}

export function buildReadingOrderTimelineEntries({ thread, dependencies }: BuildTimelineParams): TimelineEntry[] {
  const issueDeps = dependencies.filter(
    (dep) =>
      dep.target_issue_thread_id === thread.id &&
      dep.target_issue_id !== null &&
      dep.source_label !== null &&
      dep.source_label !== undefined
  )

  // Map to raw gates with necessary fields
  type RawGate = {
    targetIssueId: number
    issueNumberText: string | null
    issueNumberValue: number | null
    orderValue: number | null
    targetLabel: string
    prerequisiteLabel: string
  }

  const rawGates: RawGate[] = issueDeps.map((dep) => {
    const issueNumberText = extractIssueNumber(dep.target_label)
    const issueNumberValue = issueStringToNumber(issueNumberText ?? dep.target_label ?? null)
    const orderValue = determineOrderValue(issueNumberValue, dep.target_issue_id)
    return {
      targetIssueId: dep.target_issue_id!,
      issueNumberText,
      issueNumberValue,
      orderValue,
      targetLabel: dep.target_label ?? 'Issue gate',
      prerequisiteLabel: dep.source_label ?? 'Prerequisite',
    }
  })

  // Group gates by targetIssueId
  const gateGroups = new Map<number, RawGate[]>()
  for (const gate of rawGates) {
    const existing = gateGroups.get(gate.targetIssueId) ?? []
    existing.push(gate)
    gateGroups.set(gate.targetIssueId, existing)
  }

  // Create grouped gates
  type GroupedGate = {
    targetIssueId: number
    issueNumberText: string | null
    issueNumberValue: number | null
    orderValue: number | null
    targetLabel: string
    prerequisiteLabels: string[]
  }

  const groupedGates: GroupedGate[] = []
  for (const [targetIssueId, gates] of gateGroups) {
    const first = gates[0]
    groupedGates.push({
      targetIssueId,
      issueNumberText: first.issueNumberText,
      issueNumberValue: first.issueNumberValue,
      orderValue: first.orderValue,
      targetLabel: first.targetLabel,
      prerequisiteLabels: gates.map((g) => g.prerequisiteLabel),
    })
  }

  // Sort grouped gates by orderValue
  const sortedGates = groupedGates.sort((a, b) =>
    compareOrder(a.orderValue, b.orderValue, a.targetLabel, b.targetLabel)
  )

  const nextIssueNumberValue = issueStringToNumber(thread.next_unread_issue_number ?? null)
  const nextOrderValue = determineOrderValue(nextIssueNumberValue, thread.next_unread_issue_id)
  const isThreadComplete = thread.issues_remaining === 0

  const entries: TimelineEntry[] = []

  if (sortedGates.length === 0) {
    const spanEntry = createSpanEntry({
      start: 1,
      end: thread.total_issues,
      label: thread.total_issues ? `Issues 1–${thread.total_issues}` : 'Issues 1+',
      nextValue: nextIssueNumberValue,
      isOpenEnded: thread.total_issues == null,
    })
    entries.push({ kind: 'span', span: spanEntry })
    return entries
  }

  // Create a span for issues before the first gate, if any
  const firstGateIssueNumber = sortedGates[0]?.issueNumberValue ?? null
  if (firstGateIssueNumber !== null && firstGateIssueNumber > 1) {
    const span = createSpanEntry({
      start: 1,
      end: firstGateIssueNumber - 1,
      label: `Issues 1–${firstGateIssueNumber - 1}`,
      nextValue: nextIssueNumberValue,
      isOpenEnded: false,
    })
    entries.push({ kind: 'span', span })
  }

  // Add gate entries (no intermediate spans)
  let lastGateIssueNumber: number | null = null
   for (const gate of sortedGates) {
     const status = resolveGateStatus({
       isThreadComplete,
       gateValue: gate.orderValue,
       nextValue: nextOrderValue,
       targetIssueId: gate.targetIssueId,
       nextIssueId: thread.next_unread_issue_id,
     })

     entries.push({
       kind: 'gate',
       gate: {
         targetIssueId: gate.targetIssueId,
         issueNumberText: gate.issueNumberText,
         issueNumberValue: gate.issueNumberValue,
         targetLabel: gate.targetLabel,
         prerequisiteLabels: gate.prerequisiteLabels,
         status,
         isCurrent: status === 'blocked',
       },
     })
     if (gate.issueNumberValue !== null) {
       lastGateIssueNumber = gate.issueNumberValue
     }
   }

  // Create a span for issues after the last gate, if any
  const afterStart = (lastGateIssueNumber ?? 0) + 1
  if (thread.total_issues !== null && afterStart <= thread.total_issues) {
    const span = createSpanEntry({
      start: afterStart,
      end: thread.total_issues,
      label: `Issues ${afterStart}–${thread.total_issues}`,
      nextValue: nextIssueNumberValue,
      isOpenEnded: false,
    })
    entries.push({ kind: 'span', span })
  } else if (thread.total_issues === null) {
    // For open-ended threads, always show the span after the last gate
    const span = createSpanEntry({
      start: afterStart,
      end: null,
      label: `Issues ${afterStart}+`,
      nextValue: nextIssueNumberValue,
      isOpenEnded: true,
    })
    entries.push({ kind: 'span', span })
  }

  return entries
}

function resolveGateStatus({
  isThreadComplete,
  gateValue,
  nextValue,
  targetIssueId,
  nextIssueId,
}: {
  isThreadComplete: boolean
  gateValue: number | null
  nextValue: number | null
  targetIssueId: number | null
  nextIssueId: number | null
}): GateStatus {
  if (isThreadComplete) {
    return 'satisfied'
  }

  if (gateValue !== null && nextValue !== null) {
    if (gateValue < nextValue) {
      return 'satisfied'
    }
    if (gateValue === nextValue) {
      return 'blocked'
    }
    return 'dormant'
  }

  if (targetIssueId !== null && nextIssueId !== null && targetIssueId === nextIssueId) {
    return 'blocked'
  }

  return 'dormant'
}

function createSpanEntry({
  start,
  end,
  label,
  nextValue,
  isOpenEnded,
}: {
  start: number | null
  end: number | null
  label: string
  nextValue: number | null
  isOpenEnded: boolean
}): TimelineSpanEntry {
  const isCurrent =
    nextValue !== null &&
    start !== null &&
    ((end !== null && nextValue >= start && nextValue <= end) || (end === null && nextValue >= start))

  return {
    id: `span-${start ?? 'unknown'}-${end ?? 'open'}`,
    startNumber: start,
    endNumber: end,
    isOpenEnded,
    label,
    isCurrent,
  }
}
