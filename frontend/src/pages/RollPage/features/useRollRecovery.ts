import { useCallback } from 'react'
import { threadsApi } from '../../services/api'
import { useRollPageState, type RollPageStateSetters } from '../useRollPageState'
import type { RatingThread, ThreadMetadata } from '../types'

export function useRollRecovery(setters: RollPageStateSetters, enterRatingView: (threadId: number | null, result: number | null, metadata: ThreadMetadata | null) => Promise<void>) {
  const handleReadStale = useCallback(async (staleThread: any) => {
    if (!staleThread) return
    try {
      const response = await threadsApi.setPending(staleThread.id)
      const threadMetadata: ThreadMetadata = {
        id: response.thread_id, title: response.title, format: response.format,
        issues_remaining: response.issues_remaining, queue_position: response.queue_position,
        total_issues: response.total_issues, reading_progress: response.reading_progress ?? null,
        issue_id: response.issue_id, issue_number: response.issue_number,
        next_issue_id: response.next_issue_id, next_issue_number: response.next_issue_number,
        last_rolled_result: response.result ?? response.last_rolled_result,
      }
      if (response.total_issues === null) {
        setters.setThreadToMigrate(threadMetadata as RatingThread)
        setters.setShowMigrationDialog(true)
      } else {
        enterRatingView(response.thread_id, response.result, threadMetadata)
      }
    } catch (error) {
      console.error('Failed to set pending thread:', error)
    }
  }, [setters, enterRatingView])

  return {
    handleReadStale,
  }
}
