import { useMutation, useQuery } from '@tanstack/react-query'
import { tagsApi } from '../services/api-tags'
import type {
  AssignTagPayload,
  BulkAssignPayload,
  CreateTagPayload,
  TagTargetType,
  UpdateTagPayload,
} from '../services/api-tags'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterTagMutation } from '../query/cacheEffects'

/**
 * Usable tags visible to the caller, optionally filtered by name (issue #3032).
 *
 * The inline picker passes the debounced search text; the key stays canonical
 * because `queryKeys.tags.list` normalizes the filter.
 */
export function useTags(search?: string) {
  return useQuery({
    queryKey: queryKeys.tags.list(search),
    queryFn: () => tagsApi.list(search),
  })
}

export function useTag(id?: number | null) {
  return useQuery({
    queryKey: id ? queryKeys.tags.detail(id) : [],
    queryFn: () => tagsApi.get(id!),
    enabled: !!id,
  })
}

/**
 * Direct + effective tags for one target with every inheritance source.
 * Effective tags union direct assignments with all inherited parent paths and
 * retain every contributing source so the UI can navigate to each one.
 */
export function useEffectiveTags(
  targetType?: TagTargetType | null,
  targetId?: number | null,
) {
  return useQuery({
    queryKey:
      targetType && targetId ? queryKeys.tags.effective(targetType, targetId) : [],
    queryFn: () => {
      if (targetType === 'Issue') return tagsApi.effectiveForIssue(targetId!)
      if (targetType === 'Thread') return tagsApi.effectiveForThread(targetId!)
      return tagsApi.effectiveForPlan(targetId!)
    },
    enabled: !!targetType && !!targetId,
  })
}

/**
 * Bulk direct + effective tags for every issue in one thread (issue #3422).
 * The thread detail issue rows read this single query so the client never
 * issues one request per issue. Entries render read-only: direct tags as
 * solid chips, inherited tags as dashed chips.
 */
export function useThreadIssuesEffectiveTags(
  threadId?: number | null,
  enabled = true,
) {
  return useQuery({
    queryKey: threadId ? queryKeys.tags.effectiveForThreadIssues(threadId) : [],
    queryFn: () => tagsApi.threadIssuesEffective(threadId!),
    enabled: !!threadId && enabled,
  })
}

/** Usage counts plus consumer references for the delete-confirmation dialog. */
export function useTagUsage(id?: number | null) {
  return useQuery({
    queryKey: id ? queryKeys.tags.usage(id) : [],
    queryFn: () => tagsApi.usage(id!),
    enabled: !!id,
  })
}

export function useCreateTag() {
  return useMutation({
    mutationFn: (data: CreateTagPayload) => tagsApi.create(data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

export function useUpdateTag() {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: UpdateTagPayload }) =>
      tagsApi.update(id, data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

export function useDeleteTag() {
  return useMutation({
    mutationFn: (id: number) => tagsApi.delete(id),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

export function useAssignTag() {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AssignTagPayload }) =>
      tagsApi.assign(id, data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

export function useUnassignTag() {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: AssignTagPayload }) =>
      tagsApi.unassign(id, data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

/**
 * Bulk add of one tag across many targets (issue #3032).
 * The backend changes only the selected tag assignment and never replaces
 * unrelated tags on those targets.
 */
export function useBulkAssignTag() {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BulkAssignPayload }) =>
      tagsApi.bulkAssign(id, data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}

/** Bulk remove of one tag across many targets; unrelated tags are preserved. */
export function useBulkUnassignTag() {
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BulkAssignPayload }) =>
      tagsApi.bulkUnassign(id, data),
    onSuccess: async () => {
      await invalidateAfterTagMutation(queryClient)
    },
  })
}
