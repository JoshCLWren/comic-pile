import type { ComicVineRelatedIssue } from '../services/api'

export interface ComicIdentity {
  primary: string
  secondary: string | null
}

/**
 * Extracts the canonical comic identity from a ComicVine related issue.
 * Primary format: "Series Name #125"
 * Secondary: Issue title (if available)
 * Falls back to ComicVine issue ID when no human-readable identity exists;
 * shows a neutral label only when even the provider ID is unavailable.
 */
export function extractComicIdentity(issue: ComicVineRelatedIssue): ComicIdentity {
  const seriesName = issue.series_name?.trim() || ''
  const issueNumber = issue.issue_number?.trim() || ''
  const title = issue.name?.trim() || null

  let primary: string
  if (seriesName && issueNumber) {
    primary = `${seriesName} #${issueNumber}`
  } else if (seriesName) {
    primary = seriesName
  } else if (issueNumber) {
    primary = `#${issueNumber}`
  } else if (title) {
    primary = title
  } else if (issue.comicvine_issue_id) {
    primary = `ComicVine issue ${issue.comicvine_issue_id}`
  } else {
    primary = 'Untitled ComicVine issue'
  }

  return {
    primary,
    secondary: title && title !== primary ? title : null,
  }
}

/**
 * Determines the display state for a story-arc member.
 */
export type MemberState = 'read' | 'unread' | 'missing'

export function getMemberState(issue: ComicVineRelatedIssue): MemberState {
  if (issue.comicpile_matches.length === 0) {
    return 'missing'
  }
  if (issue.comicpile_matches.some((m) => m.status === 'unread')) {
    return 'unread'
  }
  return 'read'
}

/**
 * Gets the state label for display.
 */
export function getStateLabel(state: MemberState): string {
  switch (state) {
    case 'read':
      return 'Read'
    case 'unread':
      return 'Unread'
    case 'missing':
      return 'Not in ComicPile'
  }
}

/**
 * Normalizes a story-arc display name.
 * Strips common redundant suffixes, collapses whitespace, and title-cases
 * the result for consistent presentation.
 */
export function normalizeArcName(name: string): string {
  let normalized = name.trim()
  normalized = normalized.replace(/\s*\(storyline\)\s*$/i, '')
  normalized = normalized.replace(/\s*\(collect(?:ion|ed)\)\s*$/i, '')
  normalized = normalized.replace(/\s*\(trade paperback\)\s*$/i, '')
  normalized = normalized.replace(/\s*\(hardcover\)\s*$/i, '')
  normalized = normalized.replace(/\s*\(omnibus\)\s*$/i, '')
  normalized = normalized.replace(/\s{2,}/g, ' ')
  return normalized.trim()
}

/**
 * Gets the state color class for display.
 */
export function getStateColorClass(state: MemberState): string {
  switch (state) {
    case 'read':
      return 'text-emerald-400'
    case 'unread':
      return 'text-amber-400'
    case 'missing':
      return 'text-rose-400'
  }
}

export interface ArcNeighborAnchors {
  anchorBeforeThreadId: number | null
  anchorAfterThreadId: number | null
}

/**
 * Finds the story-arc neighbors surrounding a missing member.
 *
 * Walks outward from `missingIndex` through the arc's canonical issue order
 * and returns the first present member's ComicPile thread ID on each side.
 * These anchors let the import flow insert the new thread between the
 * surrounding arc members instead of blindly appending. Members with no
 * ComicPile match (or matches without a thread) are skipped.
 */
export function computeArcNeighborAnchors(
  relatedIssues: ComicVineRelatedIssue[],
  missingIndex: number,
): ArcNeighborAnchors {
  const firstThreadId = (issue: ComicVineRelatedIssue): number | null =>
    issue.comicpile_matches.find((match) => Number.isFinite(match.thread_id))?.thread_id ?? null

  let anchorBeforeThreadId: number | null = null
  for (let i = missingIndex - 1; i >= 0; i--) {
    const threadId = firstThreadId(relatedIssues[i])
    if (threadId !== null) {
      anchorBeforeThreadId = threadId
      break
    }
  }

  let anchorAfterThreadId: number | null = null
  for (let i = missingIndex + 1; i < relatedIssues.length; i++) {
    const threadId = firstThreadId(relatedIssues[i])
    if (threadId !== null) {
      anchorAfterThreadId = threadId
      break
    }
  }

  return { anchorBeforeThreadId, anchorAfterThreadId }
}