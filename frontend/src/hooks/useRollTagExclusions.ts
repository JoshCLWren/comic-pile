import { useMutation, useQuery } from '@tanstack/react-query'
import {
  rollTagExclusionApi,
  type ExcludeTagAndRerollResponse,
} from '../services/api-roll-exclusions'
import type { Tag } from '../services/api-tags'
import { queryClient } from '../query/queryClient'
import { queryKeys } from '../query/queryKeys'
import { invalidateAfterTagExclusionMutation } from '../query/cacheEffects'

/**
 * Active account-wide Roll tag exclusions (issue #3033).
 *
 * Exclusions are persistent eligibility constraints that stay active until
 * removed. On the Roll screen the bootstrap already carries them, so this
 * query mainly serves surfaces that render exclusions without the bootstrap.
 */
export function useTagExclusions() {
  return useQuery({
    queryKey: queryKeys.roll.exclusions(),
    queryFn: () => rollTagExclusionApi.list(),
  })
}

/**
 * Persist an account-wide exclusion. The mutation is the single source of
 * truth for the write; the invalidation helper triggers refetch.
 */
export function useAddTagExclusion() {
  return useMutation({
    mutationFn: (tagId: number) => rollTagExclusionApi.add(tagId),
    onSuccess: async () => {
      await invalidateAfterTagExclusionMutation(queryClient)
    },
  })
}

/** Remove an exclusion; matching candidates become eligible immediately. */
export function useRemoveTagExclusion() {
  return useMutation({
    mutationFn: (tagId: number) => rollTagExclusionApi.remove(tagId),
    onSuccess: async () => {
      await invalidateAfterTagExclusionMutation(queryClient)
    },
  })
}

export interface ExcludeTagAndRerollResult {
  excludedTag: Tag
  pendingInvalidated: boolean
  roll: ExcludeTagAndRerollResponse['roll']
}

/**
 * Exclude a tag mid-roll (issue #3033). When the pending result becomes
 * ineligible it is cleared and replaced through normal Roll selection; the
 * bootstrap invalidation re-renders Roll with the replacement. The action is
 * never recorded as a snooze or negative preference signal.
 */
export function useExcludeTagAndReroll() {
  return useMutation({
    mutationFn: async (tagId: number): Promise<ExcludeTagAndRerollResult> => {
      const response = await rollTagExclusionApi.excludeAndReroll(tagId)
      return {
        excludedTag: response.excluded_tag,
        pendingInvalidated: response.pending_invalidated,
        roll: response.roll,
      }
    },
    onSuccess: async () => {
      await invalidateAfterTagExclusionMutation(queryClient)
    },
  })
}
