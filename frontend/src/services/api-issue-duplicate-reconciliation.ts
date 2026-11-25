import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  DuplicateDetectionResponse,
  ReconcileApplyRequest,
  ReconcileApplyResponse,
  ReconcilePreviewRequest,
  ReconcilePreviewResponse,
  ReconcileUndoRequest,
  ReconcileUndoResponse,
} from '../types'

export function createIssueDuplicateReconciliationApi(client: HttpClient) {
  return {
    detect: () => client.get<DuplicateDetectionResponse>('/v2/issue-duplicate-reconciliation/detect'),
    preview: (request: ReconcilePreviewRequest) =>
      client.post<ReconcilePreviewResponse>('/v2/issue-duplicate-reconciliation/preview', request),
    apply: (request: ReconcileApplyRequest) =>
      client.post<ReconcileApplyResponse>('/v2/issue-duplicate-reconciliation/apply', request),
    undo: (request: ReconcileUndoRequest) =>
      client.post<ReconcileUndoResponse>('/v2/issue-duplicate-reconciliation/undo', request),
  }
}

export const issueDuplicateReconciliationApi =
  createIssueDuplicateReconciliationApi(defaultHttpClient())
