import { defaultHttpClient, type HttpClient } from './httpClient'

/**
 * A reusable tag: global (visible to everyone) or private (owner-only).
 * Hand-written (not from the generated OpenAPI types) because the checked-in
 * generated file predates the tag API; field names mirror `app/schemas/tags.py`.
 */
export interface Tag {
  id: number
  name: string
  normalized_name: string
  scope: 'global' | 'private'
  owner_user_id: number | null
  /** Hex `#RRGGBB` from the fixed 32-color palette. */
  color: string
  created_at: string
  updated_at: string
}

export interface TagListResponse {
  tags: Tag[]
}

export interface NearMatch {
  id: number
  name: string
  color: string
  normalized_name: string
  scope: string
}

export interface CreateTagPayload {
  name: string
  /** Palette name (e.g. `"red"`) or palette hex. Defaults to `"red"`. */
  color?: string
  scope?: 'global' | 'private'
  include_near_matches?: boolean
}

export interface CreateTagResponse {
  tag: Tag
  redirected_to_global: boolean
  near_matches: NearMatch[]
}

export interface UpdateTagPayload {
  name?: string
  color?: string
}

export type TagTargetType = 'Issue' | 'Thread' | 'ContinuityPlan'

export interface AssignTagPayload {
  target_type: TagTargetType
  target_id: number
}

export interface TagAssignment {
  id: number
  tag_id: number
  target_type: string
  target_id: number
  created_at: string
}

export interface BulkAssignPayload {
  target_type: TagTargetType
  target_ids: number[]
}

export interface BulkAssignResponse {
  tag_id: number
  target_type: string
  requested_ids: number[]
  affected_ids: number[]
  already_ids: number[]
}

export interface TagUsage {
  tag_id: number
  total_assignments: number
  assignments_by_target_type: Record<string, number>
  references_removed_by_consumers: Record<string, number>
}

export interface DeleteTagResponse {
  tag_id: number
  assignments_removed: number
  references_removed_by_consumers: Record<string, number>
}

export interface InheritanceSource {
  target_type: string
  target_id: number
  display_name: string
}

export interface EffectiveTag {
  tag: Tag
  /** True when directly assigned to the queried object (may also be inherited). */
  direct: boolean
  /** Every object whose direct assignment contributes this tag. */
  sources: InheritanceSource[]
}

export interface EffectiveTagsResponse {
  target_type: string
  target_id: number
  direct_tags: Tag[]
  effective_tags: EffectiveTag[]
}

/**
 * Bulk effective tags for every issue in one thread (issue #3422).
 * Issues without any visible tag appear with empty tag lists so clients can
 * distinguish "no tags" from missing data without fallback requests.
 */
export interface ThreadIssuesEffectiveTagsResponse {
  thread_id: number
  issues: EffectiveTagsResponse[]
}

/** Fixed 32-color palette names, mirroring `app/constants.py`. Red is default. */
export const TAG_COLOR_NAMES = [
  'red',
  'orange',
  'amber',
  'yellow',
  'lime',
  'green',
  'emerald',
  'teal',
  'cyan',
  'sky',
  'blue',
  'indigo',
  'violet',
  'purple',
  'fuchsia',
  'pink',
  'rose',
  'crimson',
  'burgundy',
  'maroon',
  'brown',
  'gold',
  'bronze',
  'khaki',
  'olive',
  'forest',
  'mint',
  'ice',
  'cobalt',
  'royal',
  'violet-deep',
  'magenta',
] as const

export type TagColorName = (typeof TAG_COLOR_NAMES)[number]

export const DEFAULT_TAG_COLOR_NAME: TagColorName = 'red'

/**
 * Fixed 32-color palette hex values, mirroring `app/constants.py`.
 * The API stores and returns hex, so the picker and dots resolve names here.
 */
export const TAG_COLOR_HEX: Record<TagColorName, string> = {
  red: '#DC2626',
  orange: '#F97316',
  amber: '#F59E0B',
  yellow: '#EAB308',
  lime: '#84CC16',
  green: '#22C55E',
  emerald: '#10B981',
  teal: '#14B8A6',
  cyan: '#06B6D4',
  sky: '#0EA5E9',
  blue: '#3B82F6',
  indigo: '#6366F1',
  violet: '#8B5CF6',
  purple: '#A855F7',
  fuchsia: '#D946EF',
  pink: '#EC4899',
  rose: '#F43F5E',
  crimson: '#B91C1C',
  burgundy: '#7F1D1D',
  maroon: '#78350F',
  brown: '#92400E',
  gold: '#D97706',
  bronze: '#B45309',
  khaki: '#A16207',
  olive: '#65A30D',
  forest: '#15803D',
  mint: '#34D399',
  ice: '#22D3EE',
  cobalt: '#2563EB',
  royal: '#4F46E5',
  'violet-deep': '#7C3AED',
  magenta: '#E879F9',
}

/** Resolve a palette hex (any casing) to its color name, if it is in the palette. */
export function tagColorName(hex: string): TagColorName | null {
  const normalized = hex.trim().toLowerCase()
  for (const name of TAG_COLOR_NAMES) {
    if (TAG_COLOR_HEX[name].toLowerCase() === normalized || name === normalized) {
      return name
    }
  }
  return null
}

/**
 * Tag API service (issue #3032).
 * Provides CRUD, search, assignment, bulk assignment, usage preview for the
 * delete-confirmation dialog, and effective-tag reads with inheritance sources.
 */
export function createTagsApi(client: HttpClient) {
  return {
    /** List tags visible to the caller, optionally filtered by name. */
    list: async (search?: string): Promise<TagListResponse> => {
      const trimmed = search?.trim()
      return client.get<TagListResponse>('/v1/tags/', {
        params: trimmed ? { search: trimmed } : undefined,
      })
    },
    get: (id: number) => client.get<Tag>(`/v1/tags/${id}/`),
    create: (data: CreateTagPayload) =>
      client.post<CreateTagResponse, CreateTagPayload>('/v1/tags/', data),
    update: (id: number, data: UpdateTagPayload) =>
      client.put<Tag, UpdateTagPayload>(`/v1/tags/${id}/`, data),
    delete: (id: number) => client.delete<DeleteTagResponse>(`/v1/tags/${id}/`),
    usage: (id: number) => client.get<TagUsage>(`/v1/tags/${id}/usage/`),
    assign: (id: number, data: AssignTagPayload) =>
      client.post<TagAssignment, AssignTagPayload>(`/v1/tags/${id}/assign/`, data),
    unassign: (id: number, data: AssignTagPayload) =>
      client.delete<TagAssignment>(`/v1/tags/${id}/unassign/`, { data }),
    /** Attach one tag to many targets; unrelated tags are never touched. */
    bulkAssign: (id: number, data: BulkAssignPayload) =>
      client.post<BulkAssignResponse, BulkAssignPayload>(
        `/v1/tags/${id}/bulk-assign/`,
        data,
      ),
    /** Detach one tag from many targets; unrelated tags are never touched. */
    bulkUnassign: (id: number, data: BulkAssignPayload) =>
      client.post<BulkAssignResponse, BulkAssignPayload>(
        `/v1/tags/${id}/bulk-unassign/`,
        data,
      ),
    effectiveForIssue: (issueId: number) =>
      client.get<EffectiveTagsResponse>(`/v1/tags/effective/issue/${issueId}/`),
    effectiveForThread: (threadId: number) =>
      client.get<EffectiveTagsResponse>(`/v1/tags/effective/thread/${threadId}/`),
    /**
     * Bulk effective tags for every issue in one thread (issue #3422).
     * Powers the thread detail issue rows so the client never issues one
     * request per issue.
     */
    threadIssuesEffective: (threadId: number) =>
      client.get<ThreadIssuesEffectiveTagsResponse>(
        `/v1/tags/effective/thread/${threadId}/issues/`,
      ),
    effectiveForPlan: (planId: number) =>
      client.get<EffectiveTagsResponse>(`/v1/tags/effective/plan/${planId}/`),
  }
}

export const tagsApi = createTagsApi(defaultHttpClient())
