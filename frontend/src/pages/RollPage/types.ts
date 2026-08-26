import type { Thread, SessionThread, RollResponse } from '../../types'

export type RatingThread = Pick<
  Thread,
  'id' | 'title' | 'format' | 'issues_remaining' | 'queue_position' | 'total_issues' | 'reading_progress'
> &
  Pick<SessionThread, 'issue_id' | 'issue_number' | 'next_issue_id' | 'next_issue_number' | 'last_rolled_result'> & {
    /** Concise, reader-facing reason for this roll selection (null when none) */
    explanation?: string | null
  }

export type ThreadMetadata = Partial<RollResponse & SessionThread & { result?: number }>