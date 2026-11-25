import { describe, expect, it } from 'vitest'

import { createIssueDuplicateReconciliationApi } from '../services/api-issue-duplicate-reconciliation'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const api = createIssueDuplicateReconciliationApi(client)

describe('issueDuplicateReconciliationApi', () => {
  it('reads detections from the native v2 owner-scoped endpoint', async () => {
    const response = { groups: [] }
    client.get.mockResolvedValue(response)

    await expect(api.detect()).resolves.toEqual(response)
    expect(client.get).toHaveBeenCalledWith('/v2/issue-duplicate-reconciliation/detect')
  })

  it('posts preview, apply and undo payloads to their native v2 endpoints', async () => {
    const previewRequest = {
      canonical_issue_id: 10,
      duplicate_issue_ids: [11],
      decisions: { rating_conflict: 'merge' },
    }
    const previewResponse = {
      canonical_issue_id: 10,
      duplicate_issue_ids: [11],
      canonical: {},
      duplicates: [],
      actions: [],
      warnings: [],
      can_apply: true,
      preview_token: 'token-1',
    }
    const applyRequest = { ...previewRequest, preview_token: 'token-1' }
    const applyResponse = {
      canonical_issue_id: 10,
      merged_issue_ids: [11],
      moved_event_ids: [5],
      moved_mapping_ids: [6],
      moved_list_entry_ids: [7],
      suppressed_duplicate_issue_ids: [11],
      undo_snapshot_id: 99,
      warnings: [],
    }
    const undoRequest = { reconciliation_id: 42 }
    const undoResponse = { reconciliation_id: 42, undone: true, warnings: [] }
    client.post
      .mockResolvedValueOnce(previewResponse)
      .mockResolvedValueOnce(applyResponse)
      .mockResolvedValueOnce(undoResponse)

    await expect(api.preview(previewRequest)).resolves.toEqual(previewResponse)
    await expect(api.apply(applyRequest)).resolves.toEqual(applyResponse)
    await expect(api.undo(undoRequest)).resolves.toEqual(undoResponse)

    expect(client.post).toHaveBeenNthCalledWith(
      1, '/v2/issue-duplicate-reconciliation/preview', previewRequest,
    )
    expect(client.post).toHaveBeenNthCalledWith(
      2, '/v2/issue-duplicate-reconciliation/apply', applyRequest,
    )
    expect(client.post).toHaveBeenNthCalledWith(
      3, '/v2/issue-duplicate-reconciliation/undo', undoRequest,
    )
  })
})
