import api from './api'
import type { components as OpenAPIComponents } from '../generated/openapi'
import type { ContinuityPlan } from './api-continuity-plans'

/** CBL Source (repository) */
export interface CBLSourceResponse {
  id: number
  repository: string
  revision_sha: string
  synced_at: string // ISO string
  created_at: string
  updated_at: string
}

/** CBL Source List (reading list within a source) */
export interface CBLSourceListResponse {
  id: number
  source_id: number
  source_path: string
  name: string
  declared_issue_count: number | null
  content_hash: string
  revision_sha: string
  active: boolean
  created_at: string
  updated_at: string
}

/** CBL Source with its active lists */
export interface CBLSourceWithListsResponse extends CBLSourceResponse {
  lists: CBLSourceListResponse[]
}

/** Response for uploading and parsing a CBL file */
export interface CBLUploadResponse {
  source_path: string // e.g., "uploaded.cbl"
  name: string
  declared_issue_count: number | null
  content_hash: string
  books: CBLBookResponse[]
}

/** A book entry in a CBL list */
export interface CBLBookResponse {
  position: number
  series: string
  issue_number: string
  volume_year: number | null
  publication_year: number | null
  comicvine_series_id: string | null
  comicvine_issue_id: string | null
}

/** Derived crossover-template preview returned by the CBL evidence APIs. */
export type DerivedCrossoverTemplatePreview =
  OpenAPIComponents['schemas']['DerivedCrossoverTemplatePreview']

/** One explicit reader decision for an unresolved external-list entry. */
export interface CBLReconciliationDecision {
  source_path: string
  position: number
  action: 'map' | 'skip'
  issue_id?: number | null
}

export const cblApi = {
  /** List all CBL sources with their active lists */
  listSources: () => api.get<CBLSourceWithListsResponse[]>('/api/v1/cbl/sources'),

  /** Upload and parse a CBL file */
  uploadCblFile: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<CBLUploadResponse>('/api/v1/cbl/upload', formData)
  },

  /** Preview a crossover template from an uploaded CBL file */
  previewUploadedCblTemplate: (
    file: File,
    targetStoryArcId: string | null = null
  ) => {
    const formData = new FormData()
    formData.append('file', file)
    if (targetStoryArcId !== null) {
      formData.append('target_story_arc_id', targetStoryArcId)
    }
    return api.post<DerivedCrossoverTemplatePreview>(
      '/api/v1/cbl/preview/uploaded',
      formData
    )
  },

  /** Adopt an uploaded CBL file as a continuity plan after reconciliation */
  adoptUploadedCblTemplate: (
    file: File,
    planName: string,
    laneId: string,
    laneName: string,
    orderingMode: 'strict_sequential' | 'informational',
    targetStoryArcId: string | null = null,
    reconciliations: CBLReconciliationDecision[] = [],
    skippedIssueIds: number[] = []
  ) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('plan_name', planName)
    formData.append('lane_id', laneId)
    formData.append('lane_name', laneName)
    formData.append('ordering_mode', orderingMode)
    if (targetStoryArcId !== null) {
      formData.append('target_story_arc_id', targetStoryArcId)
    }
    formData.append('reconciliations', JSON.stringify(reconciliations))
    formData.append('skipped_issue_ids', JSON.stringify(skippedIssueIds))
    return api.post<ContinuityPlan>('/api/v1/cbl/adopt/uploaded', formData)
  },

  /** The following methods reuse the existing crossover-template API for persisted lists */

  /** Preview a crossover template from persisted CBL source lists */
  previewSourceListsTemplate: (
    sourceListIds: number[],
    targetStoryArcId: string | null = null
  ) => {
    return api.post<DerivedCrossoverTemplatePreview>(
      '/api/v1/crossover-templates/preview',
      {
        source_list_ids: sourceListIds,
        target_story_arc_id: targetStoryArcId,
      }
    )
  },

  /** Adopt persisted CBL source lists as a continuity plan after reconciliation */
  adoptSourceListsTemplate: (
    sourceListIds: number[],
    planName: string,
    laneId: string,
    laneName: string,
    orderingMode: 'strict_sequential' | 'informational',
    targetStoryArcId: string | null = null,
    reconciliations: CBLReconciliationDecision[] = [],
    skippedIssueIds: number[] = []
  ) => {
    return api.post<ContinuityPlan>('/api/v1/crossover-templates/adopt', {
      source_list_ids: sourceListIds,
      plan_name: planName,
      lane_id: laneId,
      lane_name: laneName,
      ordering_mode: orderingMode,
      target_story_arc_id: targetStoryArcId,
      reconciliations,
      skipped_issue_ids: skippedIssueIds,
    })
  },
}
