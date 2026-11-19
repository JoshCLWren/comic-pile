import { useCallback, useEffect, useRef, useState } from 'react'
import { comicVineApi } from '../services/api-comicvine'
import type { ComicVineIssueCandidate, IssueIdentityResponse } from '../services/api-comicvine'
import { queryClient } from '../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  invalidateComicVineIssueIdentity,
  invalidateComicVineIssueIntelligenceMany,
} from '../query/cacheEffects'

/**
 * Mapping state of one owned canonical Issue against ComicVine.
 *
 * `provider-only` is reserved for entries that do not resolve to an owned
 * Issue yet; the shared action renders an Add/Match affordance instead of the
 * owner-scoped mapping workflow in that case.
 */
export type ComicIssueMappingStatus =
  | 'loading'
  | 'error'
  | 'unmapped'
  | 'mapped'
  | 'ambiguous'
  | 'provider-only'

export interface UseComicIssueMappingOptions {
  /** Canonical owned Issue id, or null for a provider-only entry. */
  issueId: number | null
  threadTitle: string
  issueNumber: string | null
  /**
   * Batched identity projection supplied by the parent (for example the card
   * projection from #4443). When present it is the source of truth and the
   * per-issue identity GET is skipped entirely.
   */
  initialIdentity?: IssueIdentityResponse | null
  /** Whether the identity GET may run. Defaults to true when no identity is supplied. */
  fetchEnabled?: boolean
  /** Whether this entry resolves to an owned Issue that may be mapped. */
  isOwned?: boolean
  /** Called after a confirm/replace/remove succeeds so parents can refresh. */
  onMapped?: () => void | Promise<void>
}

export interface UseComicIssueMapping {
  identity: IssueIdentityResponse | null
  status: ComicIssueMappingStatus
  isMapped: boolean
  needsIdentity: boolean
  isAmbiguous: boolean
  isLoading: boolean
  isError: boolean
  fetchIdentity: () => Promise<void>
  searchMode: 'confirm' | 'replace'
  isSearchDialogOpen: boolean
  openMappingDialog: (mode?: 'confirm' | 'replace') => void
  closeSearchDialog: () => void
  handleIdentityConfirmed: (selected?: ComicVineIssueCandidate | null) => Promise<void>
  handleSiblingsMapped: (confirmedIssueIds: number[]) => Promise<void>
  isRemoveDialogOpen: boolean
  isRemovingMapping: boolean
  removeMappingError: string | null
  openRemoveDialog: () => void
  closeRemoveDialog: () => void
  handleRemoveMapping: () => Promise<void>
}

function statusFor(identity: IssueIdentityResponse | null): ComicIssueMappingStatus {
  if (!identity) {
    return 'unmapped'
  }
  if (identity.has_confirmed_identity) {
    return 'mapped'
  }
  if (identity.has_unresolved || (identity.candidate_mappings?.length ?? 0) > 0) {
    return 'ambiguous'
  }
  return 'unmapped'
}

/**
 * Single shared ComicVine identity state and mapping workflow for one owned
 * Issue (#4450).
 *
 * The dialog is opened on demand by the caller; the hook never starts a
 * provider search. When `initialIdentity` is supplied the identity GET is
 * skipped so list surfaces fed by a batched projection issue no per-row
 * request. Failures leave the identity untouched and never block reading
 * actions owned by the parent card.
 */
export function useComicIssueMapping({
  issueId,
  initialIdentity,
  fetchEnabled,
  isOwned = true,
  onMapped,
}: UseComicIssueMappingOptions): UseComicIssueMapping {
  const [identityState, setIdentityState] = useState<IssueIdentityResponse | null>(
    () => initialIdentity ?? null,
  )
  const [isLoadingIdentity, setIsLoadingIdentity] = useState(false)
  const [identityError, setIdentityError] = useState(false)
  const [isSearchDialogOpen, setIsSearchDialogOpen] = useState(false)
  const [searchMode, setSearchMode] = useState<'confirm' | 'replace'>('confirm')
  const [isRemoveDialogOpen, setIsRemoveDialogOpen] = useState(false)
  const [isRemovingMapping, setIsRemovingMapping] = useState(false)
  const [removeMappingError, setRemoveMappingError] = useState<string | null>(null)
  const onMappedRef = useRef(onMapped)
  onMappedRef.current = onMapped

  const fetchIdentity = useCallback(async () => {
    if (!issueId || !isOwned) {
      setIdentityState(null)
      return
    }
    setIsLoadingIdentity(true)
    try {
      const state = await comicVineApi.getIssueIdentity(issueId)
      setIdentityState(state)
      setIdentityError(false)
    } catch {
      setIdentityError(true)
    } finally {
      setIsLoadingIdentity(false)
    }
  }, [issueId, isOwned])

  // A supplied batched identity is authoritative; only fetch when none exists.
  useEffect(() => {
    if (initialIdentity !== undefined && initialIdentity !== null) {
      setIdentityState(initialIdentity)
      setIdentityError(false)
      return
    }
    if (fetchEnabled === false) {
      return
    }
    void fetchIdentity()
  }, [initialIdentity, fetchEnabled, fetchIdentity])

  const handleIdentityConfirmed = useCallback(
    async (selected?: ComicVineIssueCandidate | null) => {
      if (issueId) {
        if (selected && selected.image_url !== undefined) {
          applyComicVineCorrectionOptimistically(queryClient, issueId, selected.image_url)
        }
        await invalidateComicVineIssueIntelligenceMany(queryClient, [issueId])
        await invalidateComicVineIssueIdentity(queryClient, issueId)
      }
      await fetchIdentity()
      await onMappedRef.current?.()
    },
    [fetchIdentity, issueId],
  )

  const handleSiblingsMapped = useCallback(
    async (confirmedIssueIds: number[]) => {
      if (confirmedIssueIds.length > 0) {
        await invalidateComicVineIssueIntelligenceMany(queryClient, confirmedIssueIds)
        await Promise.all(
          confirmedIssueIds.map((confirmedId) =>
            invalidateComicVineIssueIdentity(queryClient, confirmedId),
          ),
        )
      }
      await onMappedRef.current?.()
    },
    [],
  )

  const openMappingDialog = useCallback((mode: 'confirm' | 'replace' = 'confirm') => {
    setSearchMode(mode)
    setIsSearchDialogOpen(true)
  }, [])

  const closeSearchDialog = useCallback(() => setIsSearchDialogOpen(false), [])

  const openRemoveDialog = useCallback(() => {
    setRemoveMappingError(null)
    setIsRemoveDialogOpen(true)
  }, [])

  const closeRemoveDialog = useCallback(() => {
    if (!isRemovingMapping) {
      setIsRemoveDialogOpen(false)
    }
  }, [isRemovingMapping])

  const handleRemoveMapping = useCallback(async () => {
    if (!issueId) return
    setRemoveMappingError(null)
    setIsRemovingMapping(true)
    try {
      await comicVineApi.removeIdentity(issueId)
      setIsRemoveDialogOpen(false)
      await invalidateComicVineIssueIdentity(queryClient, issueId)
      await fetchIdentity()
      await onMappedRef.current?.()
    } catch (error) {
      setRemoveMappingError(
        error instanceof Error ? error.message : 'Could not remove the ComicVine mapping.',
      )
    } finally {
      setIsRemovingMapping(false)
    }
  }, [fetchIdentity, issueId])

  const status: ComicIssueMappingStatus = !isOwned
    ? 'provider-only'
    : isLoadingIdentity && identityState === null
      ? 'loading'
      : identityError && identityState === null
        ? 'error'
        : statusFor(identityState)

  return {
    identity: identityState,
    status,
    isMapped: status === 'mapped',
    needsIdentity: status === 'unmapped' || status === 'ambiguous',
    isAmbiguous: status === 'ambiguous',
    isLoading: status === 'loading',
    isError: status === 'error',
    fetchIdentity,
    searchMode,
    isSearchDialogOpen,
    openMappingDialog,
    closeSearchDialog,
    handleIdentityConfirmed,
    handleSiblingsMapped,
    isRemoveDialogOpen,
    isRemovingMapping,
    removeMappingError,
    openRemoveDialog,
    closeRemoveDialog,
    handleRemoveMapping,
  }
}
