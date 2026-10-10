import { useQuery, useMutation } from '@tanstack/react-query'
import { tagsApi } from '../services/api-tags'
import type {
  Tag,
  TagAssignmentRequest,
  TagBulkOperation,
  TagCreateRequest,
  TagUpdateRequest,
} from '../types'
import { queryKeys } from '../query/queryKeys'
import { queryClient } from '../query/queryClient'
import {
  optimisticallyAssignTag,
  optimisticallyUnassignTag,
  invalidateAfterBulkTagOperation,
  invalidateAfterTagCreate,
  invalidateAfterTagUpdate,
  invalidateAfterTagDelete,
  invalidateAfterTagAssignment,
} from '../query/cacheEffects'
import { fromTagTargetType, toTagTargetType, type TagCacheKeyType } from '../utils/tagTargetType'

/**
 * Variables for a single tag assignment change.
 *
 * `tag` is carried so the optimistic write can insert a tag that is not yet in
 * the cached effective set, and `targetLabel` is carried so the optimistic
 * source renders the real object name instead of a placeholder.
 */
export interface AssignTagVariables {
  tag: Tag
  request: TagAssignmentRequest
  targetLabel: string
}

/** Variables for removing a single tag assignment. */
export interface UnassignTagVariables {
  tagId: number
  request: TagAssignmentRequest
}

/**
 * Hook to list every tag visible to the viewer (global plus their own private).
 */
export function useTags() {
  return useQuery({
    queryKey: queryKeys.tags.list(),
    queryFn: () => tagsApi.listTags(),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })
}

/**
 * Hook to fetch a single tag by id.
 */
export function useTag(id: number) {
  return useQuery({
    queryKey: queryKeys.tags.detail(id),
    queryFn: () => tagsApi.getTag(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })
}

/**
 * Hook to create a tag.
 *
 * Resolves to the resulting tag so callers can select it immediately. When the
 * server redirects an exact normalized name onto an existing global tag, that
 * global tag is returned instead of a private duplicate.
 */
export function useCreateTag() {
  return useMutation({
    mutationFn: async (request: TagCreateRequest) => {
      const response = await tagsApi.createTag(request)
      return response.tag
    },
    onSuccess: async () => {
      await invalidateAfterTagCreate(queryClient)
    },
  })
}

/**
 * Hook to update a tag's name and/or color.
 */
export function useUpdateTag() {
  return useMutation({
    mutationFn: ({ id, request }: { id: number; request: TagUpdateRequest }) =>
      tagsApi.updateTag(id, request),
    onSuccess: async (updatedTag) => {
      await invalidateAfterTagUpdate(queryClient, updatedTag)
    },
  })
}

/**
 * Hook to delete a tag and cascade its assignments.
 */
export function useDeleteTag() {
  return useMutation({
    mutationFn: (id: number) => tagsApi.deleteTag(id),
    onSuccess: async (_, id) => {
      await invalidateAfterTagDelete(queryClient, id)
    },
  })
}

/**
 * Hook to attach a tag to an issue, thread, or Reading Plan.
 *
 * The optimistic write reshapes an already-cached effective-tag entry; the
 * server still owns the inheritance result once the mutation settles.
 */
export function useAssignTag() {
  return useMutation({
    mutationFn: ({ tag, request }: AssignTagVariables) =>
      tagsApi.assignTag(tag.id, request),
    onMutate: async ({ tag, request, targetLabel }) => {
      const cacheType = fromTagTargetType(request.target_type)
      await queryClient.cancelQueries({
        queryKey: queryKeys.tags.effective(cacheType, request.target_id),
      })

      const rollback = optimisticallyAssignTag(
        queryClient,
        tag,
        cacheType,
        request.target_id,
        targetLabel,
      )

      return { rollback }
    },
    onError: (_error, _variables, context) => {
      context?.rollback()
    },
    onSuccess: async (_data, { request }) => {
      await invalidateAfterTagAssignment(
        queryClient,
        fromTagTargetType(request.target_type),
        request.target_id,
      )
    },
  })
}

/**
 * Hook to remove a tag assignment from an issue, thread, or Reading Plan.
 */
export function useUnassignTag() {
  return useMutation({
    mutationFn: ({ tagId, request }: UnassignTagVariables) =>
      tagsApi.unassignTag(tagId, request),
    onMutate: async ({ tagId, request }) => {
      const cacheType = fromTagTargetType(request.target_type)
      await queryClient.cancelQueries({
        queryKey: queryKeys.tags.effective(cacheType, request.target_id),
      })

      const rollback = optimisticallyUnassignTag(
        queryClient,
        tagId,
        cacheType,
        request.target_id,
      )

      return { rollback }
    },
    onError: (_error, _variables, context) => {
      context?.rollback()
    },
    onSuccess: async (_data, { request }) => {
      await invalidateAfterTagAssignment(
        queryClient,
        fromTagTargetType(request.target_type),
        request.target_id,
      )
    },
  })
}

/**
 * Hook to read assignment counts before a tag is deleted.
 */
export function useTagUsage(id: number) {
  return useQuery({
    queryKey: queryKeys.tags.usage(id),
    queryFn: () => tagsApi.getTagUsage(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })
}

/**
 * Hook to read direct plus inherited tags for an issue, thread, or Reading Plan.
 */
export function useEffectiveTags(type: TagCacheKeyType, id: number) {
  return useQuery({
    queryKey: queryKeys.tags.effective(type, id),
    queryFn: () => tagsApi.getEffectiveTags(toTagTargetType(type), id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  })
}

/**
 * Hook to add or remove tags across many targets at once.
 */
export function useBulkTagOperations() {
  return useMutation({
    mutationFn: (operations: TagBulkOperation[]) => tagsApi.bulkTagOperations(operations),
    onSuccess: async () => {
      await invalidateAfterBulkTagOperation(queryClient)
    },
  })
}