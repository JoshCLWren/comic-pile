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

interface BulkReadReceipt {
  key: string
  threadId: number
  operationId: number
}

/**
 * Receipts are keyed by operation id, not just thread id, so a second bulk read
 * in the same series cannot orphan the first undoable operation (#4655 F4).
 */
export function bulkReadReceiptKey(threadId: number, operationId: number): string {
  return `${BULK_READ_OPERATION_KEY_PREFIX}${threadId}:${operationId}`
}

export function writeBulkReadReceipt(threadId: number, operationId: number): void {
  window.localStorage.setItem(bulkReadReceiptKey(threadId, operationId), '1')
}

function parseReceipt(key: string, value: string | null): BulkReadReceipt | null {
  const suffix = key.slice(BULK_READ_OPERATION_KEY_PREFIX.length)
  const parts = suffix.split(':')
  if (parts.length === 2) {
    const threadId = Number(parts[0])
    const operationId = Number(parts[1])
    if (Number.isInteger(threadId) && threadId > 0 && Number.isInteger(operationId) && operationId > 0) {
      return { key, threadId, operationId }
    }
    return null
  }
  // Legacy one-receipt-per-thread key retained so in-flight undos survive an upgrade.
  const threadId = Number(suffix)
  const operationId = Number(value)
  if (Number.isInteger(threadId) && threadId > 0 && Number.isInteger(operationId) && operationId > 0) {
    return { key, threadId, operationId }
  }
  return null
}

function allReceipts(): BulkReadReceipt[] {
  const storage = window.localStorage
  const keys: string[] = []
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index)
    if (key?.startsWith(BULK_READ_OPERATION_KEY_PREFIX)) keys.push(key)
  }
  const receipts: BulkReadReceipt[] = []
  for (const key of keys) {
    const receipt = parseReceipt(key, storage.getItem(key))
    if (receipt) receipts.push(receipt)
    else storage.removeItem(key)
  }
  return receipts
}

/** Most recent still-recorded operation for one series, if any. */
export function findBulkReadReceipt(threadId: number): BulkReadReceipt | null {
  return allReceipts()
    .filter((receipt) => receipt.threadId === threadId)
    .sort((a, b) => b.operationId - a.operationId)[0] ?? null
}

export function clearBulkReadReceipt(threadId: number, operationId: number): void {
  window.localStorage.removeItem(bulkReadReceiptKey(threadId, operationId))
  const legacyKey = `${BULK_READ_OPERATION_KEY_PREFIX}${threadId}`
  if (window.localStorage.getItem(legacyKey) === String(operationId)) {
    window.localStorage.removeItem(legacyKey)
  }
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
      for (const receipt of allReceipts()) {
        try {
          const operation = await issuesApi.getReadOperation(receipt.operationId)
          if (operation.undone_at) {
            window.localStorage.removeItem(receipt.key)
          } else {
            found.push({ threadId: receipt.threadId, operation })
          }
        } catch {
          window.localStorage.removeItem(receipt.key)
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
      clearBulkReadReceipt(threadId, operationId)
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
