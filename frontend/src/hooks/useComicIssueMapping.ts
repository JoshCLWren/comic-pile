import { useCallback, useEffect, useRef, useState } from 'react'
import { comicVineApi } from '../services/api-comicvine'
import type {
  ComicVineIssueCandidate,
  IssueIdentityEdit,
  IssueIdentityResponse,
} from '../services/api-comicvine'
import { queryClient } from '../query/queryClient'
import {
  applyComicVineCorrectionOptimistically,
  clearComicVineIssueIntelligence,
  invalidateAfterIssueMappingChange,
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
  /** Alias/version intent captured when the dialog was opened (#4652). */
  mappingEdit: IssueIdentityEdit | null
  openMappingDialog: (mode?: 'confirm' | 'replace', edit?: IssueIdentityEdit) => void
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
  const shouldAutoFetchIdentity =
    initialIdentity == null && fetchEnabled !== false && isOwned && !!issueId
  const [identityState, setIdentityState] = useState<IssueIdentityResponse | null>(
    () => initialIdentity ?? null,
  )
  const [isLoadingIdentity, setIsLoadingIdentity] = useState(shouldAutoFetchIdentity)
  const [identityError, setIdentityError] = useState(false)
  const [isSearchDialogOpen, setIsSearchDialogOpen] = useState(false)
  const [searchMode, setSearchMode] = useState<'confirm' | 'replace'>('confirm')
  const [mappingEdit, setMappingEdit] = useState<IssueIdentityEdit | null>(null)
  const [isRemoveDialogOpen, setIsRemoveDialogOpen] = useState(false)
  const [isRemovingMapping, setIsRemovingMapping] = useState(false)
  const [removeMappingError, setRemoveMappingError] = useState<string | null>(null)
  const onMappedRef = useRef(onMapped)
  onMappedRef.current = onMapped
  const removalIdentityRef = useRef<{ issueId: number; identity: IssueIdentityResponse } | null>(null)

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
      // #4652: a completed GET is authoritative. A version captured when the
      // dialog opened is stale after a 409, so rebase the edit to keep only the
      // authored alias intent. Both dialog callers then fall back to the fresh
      // identity_version for their retried write instead of replaying the
      // rejected version forever.
      setMappingEdit((previous) => {
        if (previous == null || previous.expectedVersion === undefined) return previous
        const rebased: IssueIdentityEdit = { ...previous }
        delete rebased.expectedVersion
        return Object.keys(rebased).length > 0 ? rebased : null
      })
      // A completed GET is authoritative, including a concurrent remap. The
      // removal guard only bridges failed or still-pending reconciliation.
      if (removalIdentityRef.current?.issueId === issueId) {
        removalIdentityRef.current = null
      }
    } catch {
      setIdentityError(true)
    } finally {
      setIsLoadingIdentity(false)
    }
  }, [issueId, isOwned])

  // A supplied batched identity is authoritative; only fetch when none exists.
  useEffect(() => {
    if (removalIdentityRef.current && removalIdentityRef.current.issueId !== issueId) {
      removalIdentityRef.current = null
    }
    if (initialIdentity !== undefined && initialIdentity !== null) {
      const removal = removalIdentityRef.current
      if (
        removal?.issueId === issueId
        && statusFor(initialIdentity) !== statusFor(removal.identity)
      ) {
        // A failed card refresh can replay the pre-removal projection. Keep
        // the committed DELETE result until reconciliation catches up.
        return
      }
      if (removal?.issueId === issueId) removalIdentityRef.current = null
      setIdentityState(initialIdentity)
      setIdentityError(false)
      return
    }
    if (fetchEnabled === false) {
      return
    }
    void fetchIdentity()
  }, [initialIdentity, fetchEnabled, fetchIdentity, issueId])

  const handleIdentityConfirmed = useCallback(
    async (selected?: ComicVineIssueCandidate | null) => {
      removalIdentityRef.current = null
      if (issueId) {
        if (selected && selected.image_url !== undefined) {
          applyComicVineCorrectionOptimistically(queryClient, issueId, selected.image_url)
        }
        await invalidateComicVineIssueIntelligenceMany(queryClient, [issueId])
        await invalidateComicVineIssueIdentity(queryClient, issueId)
      }
      await fetchIdentity()
      await invalidateAfterIssueMappingChange(queryClient)
      await onMappedRef.current?.()
    },
    [fetchIdentity, issueId],
  )

  const handleSiblingsMapped = useCallback(
    async (confirmedIssueIds: number[]) => {
      if (issueId && confirmedIssueIds.includes(issueId)) {
        removalIdentityRef.current = null
      }
      if (confirmedIssueIds.length > 0) {
        await invalidateComicVineIssueIntelligenceMany(queryClient, confirmedIssueIds)
        await Promise.all(
          confirmedIssueIds.map((confirmedId) =>
            invalidateComicVineIssueIdentity(queryClient, confirmedId),
          ),
        )
      }
      await invalidateAfterIssueMappingChange(queryClient)
      await onMappedRef.current?.()
    },
    [issueId],
  )

  const openMappingDialog = useCallback((
    mode: 'confirm' | 'replace' = 'confirm',
    edit: IssueIdentityEdit = {},
  ) => {
    setSearchMode(mode)
    setMappingEdit(Object.keys(edit).length > 0 ? edit : null)
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
      const removedIdentity = await comicVineApi.removeIdentity(issueId)
      // The DELETE response is authoritative. Keep the successful removal
      // visible even if the follow-up identity reconciliation cannot load.
      removalIdentityRef.current = { issueId, identity: removedIdentity }
      setIdentityState(removedIdentity)
      setIdentityError(false)
      setIsRemoveDialogOpen(false)
      await clearComicVineIssueIntelligence(queryClient, issueId)
      await invalidateComicVineIssueIdentity(queryClient, issueId)
      await fetchIdentity()
      await invalidateAfterIssueMappingChange(queryClient)
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
    mappingEdit,
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
