import { api } from './api'
import type { 
  CBLAdoptionPreviewResponse,
  CBLAdoptionPlanRequest,
  CBLSourceFingerprintResponse
} from '../types'

export const cblApi = {
  getReconciliation: (listId: number) => 
    api.get<{ [key: string]: any }>(`/api/v1/issue-identity/cbl/${listId}/reconciliation`),
  
  getAdoptionPreview: (listId: number) => 
    api.get<CBLAdoptionPreviewResponse>(`/api/v1/issue-identity/cbl/${listId}/adoption-preview`),
  
  getAdoptionPlan: (listId: number, request: CBLAdoptionPlanRequest) => 
    api.post<CBLAdoptionPreviewResponse>(`/api/v1/issue-identity/cbl/${listId}/adoption-plan`, request),
  
  // Additional methods for user-provided CBL files would go here
}