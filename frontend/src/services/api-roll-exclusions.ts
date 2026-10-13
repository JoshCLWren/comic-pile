import { defaultHttpClient, type HttpClient } from './httpClient'
import type { Tag } from './api-tags'
import type { RollResponse } from '../types'

/** The user's active account-wide Roll tag exclusions (issue #3033). */
export interface TagExclusionListResponse {
  excluded_tags: Tag[]
}

/** Outcome of a mid-roll exclusion with neutral auto-reroll. */
export interface ExcludeTagAndRerollResponse {
  excluded_tag: Tag
  pending_invalidated: boolean
  roll: RollResponse | null
}

/**
 * Roll tag-exclusion API service (issue #3033).
 * Persistent account-wide eligibility constraints: exclusions stay active
 * until removed and never record a snooze or preference signal.
 */
export function createRollTagExclusionApi(client: HttpClient) {
  return {
    /** List the user's active excluded tags. */
    list: () => client.get<TagExclusionListResponse>('/v1/roll/tag-exclusions/'),
    /** Persist an exclusion. Idempotent: already-excluded tags return as-is. */
    add: (tagId: number) =>
      client.post<Tag, { tag_id: number }>('/v1/roll/tag-exclusions/', {
        tag_id: tagId,
      }),
    /** Remove an exclusion; matching candidates become eligible immediately. */
    remove: (tagId: number) =>
      client.delete<Tag>(`/v1/roll/tag-exclusions/${tagId}/`),
    /**
     * Exclude a tag mid-roll. When the pending result becomes ineligible it
     * is cleared and replaced through normal Roll selection.
     */
    excludeAndReroll: (tagId: number) =>
      client.post<ExcludeTagAndRerollResponse>(
        `/v1/roll/tag-exclusions/${tagId}/exclude-and-reroll/`,
      ),
  }
}

export const rollTagExclusionApi =
  createRollTagExclusionApi(defaultHttpClient())
