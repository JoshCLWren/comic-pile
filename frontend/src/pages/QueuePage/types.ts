import type { Issue } from '../../types'

export interface ManualCreatorCredit {
  name: string
  roles: string[]
}

export type IssueMutation =
  | { id: number; type: 'delete'; issueId: number }
  | { id: number; type: 'reorder'; issueIds: number[] }
  | { id: number; type: 'toggle'; issueId: number; nextStatus: Issue['status'] }
  | { id: number; type: 'create'; issueRange: string }

export type QueuedIssueMutation =
  | { type: 'delete'; issueId: number }
  | { type: 'reorder'; issueIds: number[] }
  | { type: 'toggle'; issueId: number; nextStatus: Issue['status'] }
  | { type: 'create'; issueRange: string }

export type QueueFormState = {
  title: string
  format: string
  issuesRemaining: number
  notes: string
  issues: string
  lastIssueRead: number
  manualCreatorCredits: ManualCreatorCredit[]
}

/** Body of an edit mutation derived from the queue form state. */
export interface EditThreadData {
  title: string
  format: string
  notes: string | null
  issues_remaining?: number
  manual_creator_credits?: ManualCreatorCredit[]
}

export const DEFAULT_CREATE_STATE: QueueFormState = {
  title: '',
  format: 'Comic',
  issuesRemaining: 1,
  notes: '',
  issues: '',
  lastIssueRead: 0,
  manualCreatorCredits: [],
}

export const FORMAT_OPTIONS = ['Comic', 'Manga', 'Trade Paperback', 'Graphic Novel', 'Digital', 'Other'] as const