import type { ComicVineRelatedIssue } from '../services/api'

export interface ComicIdentity {
  primary: string
  secondary: string | null
}

/**
 * Extracts the canonical comic identity from a ComicVine related issue.
 * Primary format: "Series Name #125"
 * Secondary: Issue title (if available)
 * Falls back to a neutral label when no human-readable identity exists;
 * the raw provider issue ID is never shown to readers.
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