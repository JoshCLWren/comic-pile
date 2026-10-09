import { useQuery, useMutation } from '@tanstack/react-query'
import { tagsApi } from '../services/api-tags'
import type {
  Tag,
  TagAssignment,
  TagInheritanceSource,
  EffectiveTag,
  TagCreateRequest,
  TagUpdateRequest,
  TagAssignmentRequest,
  TagUsageInfo,
  TagNearMatch,
  TagSearchResult,
  TagTargetType,
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

/**
 * Hook to list all visible tags (global + user's private)
 */
export function useTags() {
  return useQuery({
    queryKey: queryKeys.tags.list(),
    queryFn: () => tagsApi.listTags(),
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Hook to get a specific tag by ID
 */
export function useTag(id: number) {
  return useQuery({
    queryKey: queryKeys.tags.detail(id),
    queryFn: () => tagsApi.getTag(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Hook to create a new tag
 */
export function useCreateTag() {
  return useMutation({
    mutationFn: (request: TagCreateRequest) => tagsApi.createTag(request),
    onSuccess: async () => {
      await invalidateAfterTagCreate(queryClient)
    },
  })
}

/**
 * Hook to update an existing tag
 */
export function useUpdateTag() {
  return useMutation({
    mutationFn: ({ id, request }: { id: number; request: TagUpdateRequest }) =>
      tagsApi.updateTag(id, request),
    onSuccess: async (updatedTag, { id }) => {
      const tag = await tagsApi.getTag(id)
      await invalidateAfterTagUpdate(queryClient, tag)
    },
  })
}

/**
 * Hook to delete a tag
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
 * Hook to assign a tag to a target
 */
export function useAssignTag() {
  return useMutation({
    mutationFn: ({ tagId, request }: { tagId: number; request: TagAssignmentRequest }) =>
      tagsApi.assignTag(tagId, request),
    onMutate: async ({ tagId, request }) => {
      const tag = await tagsApi.getTag(tagId)
      // SAFETY: target_type is validated by the API to be 'Issue' | 'Thread' | 'ContinuityPlan'
      const rollback = optimisticallyAssignTag(
        queryClient,
        tag,
        request.target_type.toLowerCase() as 'issue' | 'thread' | 'plan',
        request.target_id
      )
      return { rollback }
    },
    onError: (_err, _vars, ctx) => {
      ctx?.rollback?.()
    },
    onSuccess: async (_, { request }) => {
      await invalidateAfterTagAssignment(
        queryClient,
        // SAFETY: target_type is validated by the API to be 'Issue' | 'Thread' | 'ContinuityPlan'
        request.target_type.toLowerCase() as 'issue' | 'thread' | 'plan',
        request.target_id
      )
    },
  })
}

/**
 * Hook to remove a tag assignment
 */
export function useUnassignTag() {
  return useMutation({
    mutationFn: ({ tagId, request }: { tagId: number; request: TagAssignmentRequest }) =>
      tagsApi.unassignTag(tagId, request),
    onMutate: async ({ tagId, request }) => {
      // SAFETY: target_type is validated by the API to be 'Issue' | 'Thread' | 'ContinuityPlan'
      const rollback = optimisticallyUnassignTag(
        queryClient,
        tagId,
        request.target_type.toLowerCase() as 'issue' | 'thread' | 'plan',
        request.target_id
      )
      return { rollback }
    },
    onError: (_err, _vars, ctx) => {
      ctx?.rollback?.()
    },
    onSuccess: async (_, { request }) => {
      await invalidateAfterTagAssignment(
        queryClient,
        // SAFETY: target_type is validated by the API to be 'Issue' | 'Thread' | 'ContinuityPlan'
        request.target_type.toLowerCase() as 'issue' | 'thread' | 'plan',
        request.target_id
      )
    },
  })
}

/**
 * Hook to get tag usage statistics
 */
export function useTagUsage(id: number) {
  return useQuery({
    queryKey: queryKeys.tags.usage(id),
    queryFn: () => tagsApi.getTagUsage(id),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Hook to get effective tags (direct + inherited) for a target
 */
export function useEffectiveTags(type: 'issue' | 'thread' | 'plan', id: number) {
  return useQuery({
    queryKey: queryKeys.tags.effective(type, id),
    queryFn: () => tagsApi.getEffectiveTags(
      // SAFETY: type is constrained to 'issue' | 'thread' | 'plan' by the function signature
      type.charAt(0).toUpperCase() + type.slice(1) as TagTargetType,
      id
    ),
    enabled: !!id,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  })
}

/**
 * Hook to search for tags by name (for autocomplete)
 */
export function useTagSearch(query: string, limit: number = 10) {
  return useQuery({
    queryKey: queryKeys.tags.search(query),
    queryFn: () => tagsApi.searchTags(query, limit),
    enabled: query.length > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes,
  })
}

/**
 * Hook to get near-matches for tag creation (suggestions)
 */
export function useTagNearMatches(name: string, limit: number = 8) {
  return useQuery({
    queryKey: queryKeys.tags.nearMatches(name),
    queryFn: () => tagsApi.getNearMatches(name, limit),
    enabled: name.length > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes,
  })
}

/**
 * Hook to check if a tag name is available
 */
export function useCheckTagNameAvailability(name: string, scope: 'global' | 'private') {
  return useQuery({
    queryKey: queryKeys.tags.checkName(name, scope),
    queryFn: () => tagsApi.checkNameAvailability(name, scope),
    enabled: name.length > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes,
  })
}

/**
 * Hook to perform bulk tag operations
 */
export function useBulkTagOperations() {
  return useMutation({
    mutationFn: (operations: import('../services/api-tags').TagBulkOperation[]) =>
      tagsApi.bulkTagOperations(operations),
    onSuccess: async () => {
      await invalidateAfterBulkTagOperation(queryClient)
    },
  })
}