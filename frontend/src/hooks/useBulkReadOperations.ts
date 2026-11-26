import { useCallback, useEffect, useState } from 'react'
import {
  issuesApi as defaultIssuesApi,
  type IssueReadOperationResponse,
} from '../services/api-issues'
import { getApiErrorStatus } from '../utils/apiError'
import { queryClient } from '../query/queryClient'
import { invalidateAfterIssueEdit, invalidateAfterQueueMutation } from '../query/cacheEffects'

/** localStorage key prefix written by IssueCorrectionDialog after a bulk read. */
export const BULK_READ_OPERATION_KEY_PREFIX = 'issueReadOperation:'
const RECEIPTS_CHANGED_EVENT = 'comicpile:bulk-read-receipts-changed'

function notifyReceiptsChanged(): void {
  // A native storage event is sent to other tabs, not the writing tab.
  window.dispatchEvent(new Event(RECEIPTS_CHANGED_EVENT))
}

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
  notifyReceiptsChanged()
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
  notifyReceiptsChanged()
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
  const [discoveryMessage, setDiscoveryMessage] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let discoveryVersion = 0
    const discover = async () => {
      const version = ++discoveryVersion
      const isCurrent = () => active && version === discoveryVersion
      const found: PersistedBulkReadOperation[] = []
      const seen = new Set<number>()
      let incomplete = false
      let receipts: BulkReadReceipt[]
      try {
        receipts = allReceipts()
      } catch {
        if (isCurrent()) {
          setDiscoveryMessage('Undo receipts could not be read. Reload to retry.')
        }
        return
      }
      for (const receipt of receipts) {
        if (seen.has(receipt.operationId)) continue
        try {
          const operation = await issuesApi.getReadOperation(receipt.operationId)
          if (!isCurrent()) return
          if (operation.undone_at) {
            // Only a successful authoritative read can prove Undo is no longer
            // available. Clear legacy duplicates as well so a second receipt
            // for the same operation cannot surface a stale Undo entry.
            for (const duplicate of receipts) {
              if (duplicate.operationId === receipt.operationId) {
                window.localStorage.removeItem(duplicate.key)
              }
            }
            continue
          }
          seen.add(receipt.operationId)
          found.push({ threadId: receipt.threadId, operation })
        } catch (error: unknown) {
          if (!isCurrent()) return
          // A timeout, 5xx, expired login, or owner-scoped 404 is not proof
          // that the operation is gone. Keep the receipt so the owner can
          // recover it after reconnection or signing back into their account.
          if (getApiErrorStatus(error) !== 404) incomplete = true
        }
      }
      if (isCurrent()) {
        setOperations(found)
        setDiscoveryMessage(incomplete
          ? 'Some bulk reads could not be loaded. Undo receipts were kept; reconnect or reload to retry.'
          : null)
      }
    }
    void discover()
    const refresh = () => { void discover() }
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key.startsWith(BULK_READ_OPERATION_KEY_PREFIX)) refresh()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener(RECEIPTS_CHANGED_EVENT, refresh)
    window.addEventListener('online', refresh)
    return () => {
      active = false
      window.removeEventListener('storage', onStorage)
      window.removeEventListener(RECEIPTS_CHANGED_EVENT, refresh)
      window.removeEventListener('online', refresh)
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

  return { operations, message: message ?? discoveryMessage, undo }
}
