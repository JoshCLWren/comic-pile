import { defaultHttpClient, type HttpClient } from './httpClient'
import type {
  Tag,
  TagAssignment,
  TagAssignmentRequest,
  TagBulkOperation,
  TagCreateRequest,
  TagCreateResponse,
  TagDeleteResult,
  TagListResponse,
  TagTargetType,
  TagUpdateRequest,
  TagUsageInfo,
  EffectiveTags,
} from '../types'
import { tagTargetTypeUrlSegment } from '../utils/tagTargetType'

/** Every tag route lives under the v1 tag router and keeps its trailing slash. */
const TAG_BASE_PATH = '/v1/tags'

/**
 * Build the tag service bound to an HTTP client.
 *
 * The endpoints here mirror `app/api/tags.py`. Near-match suggestions ride on
 * tag creation (`include_near_matches`), and the client applies bulk operations
 * as one assignment call per target so each request stays within the existing
 * per-target contract.
 *
 * @param client - HTTP transport used for every tag request.
 * @returns The tag API bound to `client`.
 */
export function createTagsApi(client: HttpClient) {
  return {
    /** List every tag visible to the viewer (all global plus their own private). */
    listTags: (): Promise<Tag[]> =>
      client
        .get<TagListResponse>(`${TAG_BASE_PATH}/`)
        .then((response) => response.tags),

    /** Fetch one tag, enforcing owner-only visibility for private tags. */
    getTag: (tagId: number): Promise<Tag> => client.get<Tag>(`${TAG_BASE_PATH}/${tagId}/`),

    /**
     * Create a tag.
     *
     * The response carries `redirected_to_global` when an exact normalized name
     * matched a global tag, in which case `tag` is that global tag rather than a
     * new private duplicate.
     */
    createTag: (request: TagCreateRequest): Promise<TagCreateResponse> =>
      client.post<TagCreateResponse, TagCreateRequest>(`${TAG_BASE_PATH}/`, request),

    /** Update a tag's name and/or color. */
    updateTag: (tagId: number, request: TagUpdateRequest): Promise<Tag> =>
      client.put<Tag, TagUpdateRequest>(`${TAG_BASE_PATH}/${tagId}/`, request),

    /** Delete a tag and cascade its assignments. */
    deleteTag: (tagId: number): Promise<TagDeleteResult> =>
      client.delete<TagDeleteResult>(`${TAG_BASE_PATH}/${tagId}/`),

    /** Attach a tag to a target. Idempotent on the server. */
    assignTag: (tagId: number, request: TagAssignmentRequest): Promise<TagAssignment> =>
      client.post<TagAssignment, TagAssignmentRequest>(
        `${TAG_BASE_PATH}/${tagId}/assign/`,
        request,
      ),

    /** Remove a tag assignment from a target. */
    unassignTag: (tagId: number, request: TagAssignmentRequest): Promise<TagAssignment> =>
      client.delete<TagAssignment>(`${TAG_BASE_PATH}/${tagId}/unassign/`, {
        data: request,
      }),

    /** Return assignment counts so the UI can confirm a deletion's blast radius. */
    getTagUsage: (tagId: number): Promise<TagUsageInfo> =>
      client.get<TagUsageInfo>(`${TAG_BASE_PATH}/${tagId}/usage/`),

    /** Return direct plus inherited tags for one issue, thread, or Reading Plan. */
    getEffectiveTags: (targetType: TagTargetType, targetId: number): Promise<EffectiveTags> =>
      client.get<EffectiveTags>(
        `${TAG_BASE_PATH}/effective/${tagTargetTypeUrlSegment(targetType)}/${targetId}/`,
      ),

    /**
     * Apply bulk add/remove operations.
     *
     * The API has no bulk route, so each operation fans out to one assignment
     * call per target. Adding or removing a single tag assignment never touches
     * the issue's other tags, which is what the bulk contract requires.
     */
    async bulkTagOperations(operations: TagBulkOperation[]): Promise<void> {
      const calls = operations.flatMap((operation) =>
        operation.target_ids.map((targetId) => {
          const request: TagAssignmentRequest = {
            target_type: operation.target_type,
            target_id: targetId,
          }
          return operation.action === 'add'
            ? client.post<TagAssignment, TagAssignmentRequest>(
                `${TAG_BASE_PATH}/${operation.tag_id}/assign/`,
                request,
              )
            : client.delete<TagAssignment>(
                `${TAG_BASE_PATH}/${operation.tag_id}/unassign/`,
                { data: request },
              )
        }),
      )

      await Promise.all(calls)
    },
  }
}

export type TagsApi = ReturnType<typeof createTagsApi>

export const tagsApi = createTagsApi(defaultHttpClient())