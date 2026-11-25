import { useCallback, useEffect, useState } from 'react'
import {
  issuesApi as defaultIssuesApi,
  type IssueReadOperationResponse,
} from '../services/api-issues'
import { queryClient } from '../query/queryClient'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../query/cacheEffects'

/** localStorage key prefix written by IssueCorrectionDialog after a bulk read. */
export const BULK_READ_OPERATION_KEY_PREFIX = 'issueReadOperation:'

export interface PersistedBulkReadOperation {
  threadId: number
  operation: IssueReadOperationResponse
}

/** Named contract for the discovery hook so exported callers keep inference. */
export interface BulkReadOperationsResult {
  operations: PersistedBulkReadOperation[]
  message: string | null
  undo: (threadId: number, operationId: number) => Promise<void>
}

interface IssuesApiForDiscovery {
  getReadOperation: (operationId: number) => Promise<IssueReadOperationResponse>
  undoReadOperation: (operationId: number) => Promise<{ skipped_issue_ids: number[] }>
}

/**
 * Discover persisted, still-undoable bulk read operations across reloads and
 * tabs. The GET-by-ID endpoint alone is not a discovery path: this hook reads
 * the durable localStorage receipts, hydrates each one through the API and
 * listens for the cross-tab `storage` event (#4655 review R5).
 */
export function useBulkReadOperations(
  issuesApi: IssuesApiForDiscovery = defaultIssuesApi,
): BulkReadOperationsResult {
  const [operations, setOperations] = useState<PersistedBulkReadOperation[]>([])
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const discover = async () => {
      const found: PersistedBulkReadOperation[] = []
      const storage = window.localStorage
      const keys: string[] = []
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index)
        if (key?.startsWith(BULK_READ_OPERATION_KEY_PREFIX)) keys.push(key)
      }
      for (const key of keys) {
        const threadId = Number(key.slice(BULK_READ_OPERATION_KEY_PREFIX.length))
        const operationId = Number(storage.getItem(key))
        if (!Number.isFinite(threadId) || !Number.isFinite(operationId)) {
          storage.removeItem(key)
          continue
        }
        try {
          const operation = await issuesApi.getReadOperation(operationId)
          if (operation.undone_at) {
            storage.removeItem(key)
          } else {
            found.push({ threadId, operation })
          }
        } catch {
          storage.removeItem(key)
        }
      }
      if (active) setOperations(found)
    }
    void discover()
    const onStorage = () => { void discover() }
    window.addEventListener('storage', onStorage)
    return () => {
      active = false
      window.removeEventListener('storage', onStorage)
    }
  }, [issuesApi])

  const undo = useCallback(async (threadId: number, operationId: number) => {
    setMessage(null)
    try {
      const result = await issuesApi.undoReadOperation(operationId)
      window.localStorage.removeItem(`${BULK_READ_OPERATION_KEY_PREFIX}${threadId}`)
      setOperations((current) => current.filter((entry) => entry.operation.id !== operationId))
      setMessage(
        result.skipped_issue_ids.length > 0
          ? `Undo skipped ${result.skipped_issue_ids.length} issue(s) changed later.`
          : 'Bulk read undone.',
      )
      await invalidateAfterQueueMutation(queryClient)
      await invalidateAfterIssueEdit(queryClient, threadId)
    } catch {
      setMessage('Failed to undo bulk read operation.')
    }
  }, [issuesApi])

  return { operations, message, undo }
}
