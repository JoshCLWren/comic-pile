import type { Issue } from '../../types'

export type IssueMutation =
  | { id: number; type: 'delete'; issueId: number }
  | { id: number; type: 'reorder'; issueIds: number[] }
  | { id: number; type: 'toggle'; issueId: number; nextStatus: Issue['status'] }

export type QueuedIssueMutation =
  | { type: 'delete'; issueId: number }
  | { type: 'reorder'; issueIds: number[] }
  | { type: 'toggle'; issueId: number; nextStatus: Issue['status'] }

export type QueueFormState = {
  title: string
  format: string
  issuesRemaining: number
  notes: string
  issues: string
  lastIssueRead: number
}

export const DEFAULT_CREATE_STATE: QueueFormState = {
  title: '',
  format: 'Comics',
  issuesRemaining: 1,
  notes: '',
  issues: '',
  lastIssueRead: 0,
}

export const FORMAT_OPTIONS = ['Comics', 'Manga', 'Trade Paperback', 'Graphic Novel', 'Other'] as const