import { useQuery, useMutation } from '@tanstack/react-query'
import {
  identityInboxApi,
  type IdentityInboxConfirmPayload,
  type IdentityInboxRejectPayload,
} from '../services/api'
import { queryKeys } from '../query/queryKeys'
import { invalidateIdentityInbox } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'

const INBOX_LIMIT = 20

export function useIdentityInbox(offset: number) {
  return useQuery({
    queryKey: queryKeys.identityInbox.list({ offset, limit: INBOX_LIMIT }),
    queryFn: () => identityInboxApi.list(offset, INBOX_LIMIT),
  })
}

export function useConfirmInboxCandidate() {
  return useMutation({
    mutationFn: ({
      mappingId,
      payload,
    }: {
      mappingId: number
      payload: IdentityInboxConfirmPayload
    }) => identityInboxApi.confirm(mappingId, payload),
    onSuccess: async () => {
      await invalidateIdentityInbox(queryClient)
    },
  })
}

export function useRejectInboxCandidate() {
  return useMutation({
    mutationFn: ({
      mappingId,
      payload,
    }: {
      mappingId: number
      payload: IdentityInboxRejectPayload
    }) => identityInboxApi.reject(mappingId, payload),
    onSuccess: async () => {
      await invalidateIdentityInbox(queryClient)
    },
  })
}

export function useDeferInboxItem() {
  return useMutation({
    mutationFn: (mappingId: number) => identityInboxApi.defer(mappingId),
    onSuccess: async () => {
      await invalidateIdentityInbox(queryClient)
    },
  })
}

export function useSkipInboxItem() {
  return useMutation({
    mutationFn: (mappingId: number) => identityInboxApi.skip(mappingId),
    onSuccess: async () => {
      await invalidateIdentityInbox(queryClient)
    },
  })
}
