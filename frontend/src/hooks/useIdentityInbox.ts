import { useQuery, useMutation } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { identityInboxApi } from '../services/api-identity'
import type { IdentityInboxConfirmPayload, IdentityInboxRejectPayload } from '../services/api-identity'
import { queryKeys } from '../query/queryKeys'
import { invalidateIdentityInbox } from '../query/cacheEffects'
import { queryClient } from '../query/queryClient'

const INBOX_LIMIT = 20
const INBOX_ROUTE_PATH = '/identity-inbox'

/**
 * One page of identity-reconciliation inbox items.
 *
 * The first page response already carries the unresolved `total` that the
 * navigation badge needs, so the `/identity-inbox` route must not pay for a
 * second totals-only read of the same endpoint.
 */
export function useIdentityInbox(offset: number) {
  return useQuery({
    queryKey: queryKeys.identityInbox.list({ offset, limit: INBOX_LIMIT }),
    queryFn: () => identityInboxApi.list(offset, INBOX_LIMIT),
  })
}

/**
 * Unresolved inbox total used by the navigation badge.
 *
 * On `/identity-inbox` the page's own list response supplies the total the
 * badge would otherwise probe for. Suppressing this limit=1 read on that route
 * turns two concurrent requests to `/v1/identity-inbox` into the single page
 * request; every other route keeps the cheap probe and its 10-second
 * freshness window. A badge already cached before entering the page keeps
 * rendering; a direct cold load fills it on the next route change.
 */
export function useIdentityInboxStatus(enabled = true) {
  const { pathname } = useLocation()
  const pageOwnsTotal = pathname === INBOX_ROUTE_PATH
  return useQuery({
    queryKey: queryKeys.identityInbox.list({ offset: 0, limit: 1 }),
    queryFn: () => identityInboxApi.list(0, 1),
    select: (data) => data.total,
    staleTime: 10_000,
    enabled: enabled && !pageOwnsTotal,
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
