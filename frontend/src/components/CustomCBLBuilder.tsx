import { ReadingListReader } from './ReadingListReader'
import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { applyCommittedReadingPlan, applyCreatedCustomCBL, applyUpdatedCustomCBL, applyDeletedCustomCBL } from '../query/cacheEffects'
import { queryKeys } from '../query/queryKeys'
import Modal from './Modal'
import {
  customCBLApi,
  type CustomCBLEntry,
  type CustomCBLIssueSearchResult,
  type CustomCBLWrite,
  type ReadingListEntryIntent,
  type ReadingListGate,
  type ReadingListMode,
  type ReadingListPredecessorChange,
} from '../services/api-custom-cbl'
import type { ContinuityPlan } from '../services/api-continuity-plans'
import {
  cblSourcesApi,
  type CBLSourceListDiscoveryItem,
} from '../services/api-cbl-sources'
import CblReplaceReviewPanel from './CblReplaceReviewPanel'
import ReadingListEntryCard from './ReadingListEntryCard'
import { buildReplacementModel } from '../utils/readingListReplacementModel'
import ConfirmDialog from './ConfirmDialog'
import {
  computeEntryRequirements,
  decodeCustomCBLError,
  describeCyclePath,
  describePredecessorChange,
} from '../utils/readingListAuthoring'

interface CustomCBLBuilderProps {
  planId?: number
  initialListId?: number
  disabled?: boolean
  onApplied?: (plan: ContinuityPlan) => void
  onPendingChange?: (pending: boolean) => void
}

const DEFAULT_MODE: ReadingListMode = 'loose'
const DEFAULT_GATE: ReadingListGate = 'none'
const ENTRY_PAGE_SIZE = 30

function normalizePositions(entries: CustomCBLEntry[]): CustomCBLEntry[] {
  return entries.map((entry, position) => ({
    ...entry,
    position,
    is_checkpoint: Boolean(entry.is_checkpoint),
    skipped: Boolean(entry.skipped),
    gate: entry.gate ?? DEFAULT_GATE,
  }))
}

function draftEntry(result: CustomCBLIssueSearchResult, position: number): CustomCBLEntry {
  return {
    id: -result.issue_id,
    position,
    issue_id: result.issue_id,
    thread_id: result.thread_id,
    series_name: result.series_name,
    issue_number: result.issue_number,
    status: result.status,
    is_checkpoint: false,
    gate: DEFAULT_GATE,
    skipped: false,
  }
}

function sameEntries(left: CustomCBLEntry[], right: CustomCBLEntry[]): boolean {
  return (
    left.length === right.length &&
    left.every((entry, index) => {
      const other = right[index]
      return (
        other !== undefined &&
        entry.issue_id === other.issue_id &&
        entry.gate === (other.gate ?? DEFAULT_GATE) &&
        entry.skipped === (other.skipped ?? false) &&
        Boolean(entry.is_checkpoint) === Boolean(other.is_checkpoint)
      )
    })
  )
}

function checkpointTargetsFor(entries: readonly CustomCBLEntry[]): Record<number, number[]> | null {
  const targets: Record<number, number[]> = {}
  for (const entry of entries) {
    const values = entry.checkpoint_target_issue_ids
    if (entry.is_checkpoint && values && values.length > 0) {
      targets[entry.issue_id] = [...values]
    }
  }
  return Object.keys(targets).length > 0 ? targets : null
}

function buildWritePayload(
  name: string,
  description: string,
  mode: ReadingListMode,
  entries: CustomCBLEntry[],
  confirmed: ReadingListPredecessorChange[] | null,
  checkpointTargets: Record<number, number[]> | null = null,
): CustomCBLWrite {
  const issueIds: number[] = []
  const checkpointIds: number[] = []
  const entryIntents: Record<number, ReadingListEntryIntent> = {}
  for (const entry of entries) {
    issueIds.push(entry.issue_id)
    if (entry.is_checkpoint) checkpointIds.push(entry.issue_id)
    entryIntents[entry.issue_id] = { gate: entry.gate, skipped: entry.skipped }
  }
  const payload: CustomCBLWrite = {
    name: name.trim(),
    description: description.trim() || null,
    mode,
    issue_ids: issueIds,
    entry_intents: entryIntents,
    checkpoint_issue_ids: checkpointIds,
  }
  if (confirmed) payload.confirmed_predecessor_changes = confirmed
  if (checkpointTargets) payload.checkpoint_targets = checkpointTargets
  return payload
}

function messageFor(error: unknown, fallback: string): string {
  const detail = decodeCustomCBLError(error)
  if (detail.message) return detail.message
  if (error instanceof Error && error.message) return error.message
  return fallback
}

/**
 * Raised when the owned list changed after the reader opened the replacement
 * review, so the reviewed before/after would no longer describe the target.
 */
class StaleReadingListReviewError extends Error {
  constructor() {
    super('This Reading List changed after you reviewed it. Reopen the replacement review before saving.')
    this.name = 'StaleReadingListReviewError'
  }
}

/**
 * Raised when another save changed the list after the replacement Undo snapshot
 * was taken. Applying that snapshot would silently discard the later edits.
 */
class StaleReadingListUndoError extends Error {
  constructor() {
    super('This Reading List changed after the replacement, so Undo is no longer available. Nothing was changed.')
    this.name = 'StaleReadingListUndoError'
  }
}

export default function CustomCBLBuilder({
  planId,
  initialListId,
  disabled = false,
  onApplied,
  onPendingChange,
}: CustomCBLBuilderProps) {
  const queryClient = useQueryClient()
  const issueSearchInput = useRef<HTMLInputElement>(null)
  const issueSearchResults = useRef<HTMLDivElement>(null)
  const [readerOpen, setReaderOpen] = useState(false)
  const [open, setOpen] = useState(initialListId !== undefined)
  const [selectedId, setSelectedId] = useState<number | null>(initialListId ?? null)
  const [loadedListId, setLoadedListId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [mode, setMode] = useState<ReadingListMode>(DEFAULT_MODE)
  const [entries, setEntries] = useState<CustomCBLEntry[]>([])
  const [entrySearch, setEntrySearch] = useState('')
  const [entryPage, setEntryPage] = useState(0)
  const [jumpPosition, setJumpPosition] = useState('')
  const [expandedEntryOptions, setExpandedEntryOptions] = useState<number | null>(null)
  const [moveDestinations, setMoveDestinations] = useState<Record<number, string>>({})
  const [issueQuery, setIssueQuery] = useState('')
  const [submittedIssueQuery, setSubmittedIssueQuery] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [exportError, setExportError] = useState<Error | null>(null)
  const [replaceOpen, setReplaceOpen] = useState(false)
  const [cblQuery, setCblQuery] = useState('')
  const [cblSubmittedQuery, setCblSubmittedQuery] = useState('')
  const [cblSource, setCblSource] = useState<CBLSourceListDiscoveryItem | null>(null)
  const [replaceBaseline, setReplaceBaseline] = useState<string | null>(null)
  const [undoPayload, setUndoPayload] = useState<CustomCBLWrite | null>(null)
  const [undoBaseline, setUndoBaseline] = useState<string | null>(null)
  const [replaceConfirmation, setReplaceConfirmation] = useState<{
    issueIds: number[]
    changes: ReadingListPredecessorChange[]
  } | null>(null)
  const [undoConfirmation, setUndoConfirmation] = useState<
    ReadingListPredecessorChange[] | null
  >(null)
  const [replaceError, setReplaceError] = useState<string | null>(null)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)

  const listsQuery = useQuery({
    queryKey: queryKeys.customCBLs.list(),
    queryFn: customCBLApi.list,
    enabled: open,
  })
  const detailQuery = useQuery({
    queryKey: selectedId ? queryKeys.customCBLs.detail(selectedId) : queryKeys.customCBLs.detail(0),
    queryFn: () => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.get(selectedId)
    },
    enabled: selectedId !== null,
  })
  const issueSearchQuery = useQuery({
    queryKey: queryKeys.customCBLs.issueSearch(submittedIssueQuery),
    queryFn: () => customCBLApi.searchIssues(submittedIssueQuery),
    enabled: selectedId !== null && submittedIssueQuery.length > 0,
  })
  const cblSourcesQuery = useQuery({
    queryKey: queryKeys.cblSources.search(cblSubmittedQuery),
    queryFn: () => cblSourcesApi.discover(cblSubmittedQuery),
    enabled: open && replaceOpen && cblSubmittedQuery.length > 0,
  })
  const cblPreviewQuery = useQuery({
    queryKey: cblSource
      ? queryKeys.cblSources.preview(cblSource.id)
      : queryKeys.cblSources.preview(0),
    queryFn: () => {
      if (!cblSource) throw new Error('Choose a CBL source first.')
      return cblSourcesApi.preview(cblSource.id)
    },
    enabled: open && replaceOpen && cblSource !== null,
  })

  useEffect(() => {
    const list = detailQuery.data
    if (!list) return
    // Only (re)seed the form when the selected list identity changes. React Query
    // can emit new data for the same list (refetch, cache write, or the second
    // run this effect triggers via setLoadedListId); reseeding then would discard
    // in-progress mode/gate/skip edits before the reader saves them.
    if (list.id === loadedListId) return
    setName(list.name)
    setDescription(list.description ?? '')
    setMode(list.mode ?? DEFAULT_MODE)
    setEntries(normalizePositions(list.entries))
    setEntrySearch('')
    setEntryPage(0)
    setJumpPosition('')
    setExpandedEntryOptions(null)
    setMoveDestinations({})
    setLoadedListId(list.id)
    setMessage(null)
    setExportError(null)
  }, [detailQuery.data, loadedListId])

  const createMutation = useMutation({
    mutationFn: () => customCBLApi.create({ name: newName.trim(), issue_ids: [] }),
    onSuccess: async (created) => {
      await applyCreatedCustomCBL(queryClient, created)
      saveMutation.reset()
      setSelectedId(created.id)
      setNewName('')
      setMessage('Custom CBL created.')
    },
  })
  const saveMutation = useMutation({
    mutationFn: (confirmed: ReadingListPredecessorChange[] | null) => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      return customCBLApi.update(
        selectedId,
        buildWritePayload(name, description, mode, entries, confirmed),
      )
    },
    onSuccess: async (saved) => {
      await applyUpdatedCustomCBL(queryClient, saved)
      setEntries(normalizePositions(saved.entries))
      setMode(saved.mode ?? DEFAULT_MODE)
      // A later save makes the replacement snapshot stale: undoing it would
      // silently discard the membership change that was just saved.
      setUndoPayload(null)
      setUndoBaseline(null)
      setMessage('Custom CBL saved.')
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (listId: number) => customCBLApi.delete(listId),
    onSuccess: async () => {
      if (selectedId) await applyDeletedCustomCBL(queryClient, selectedId)
      saveMutation.reset()
      setConfirmDeleteOpen(false)
      setSelectedId(null)
      setLoadedListId(null)
      setName('')
      setDescription('')
      setMode(DEFAULT_MODE)
      setEntries([])
      setMessage('Custom CBL deleted.')
    },
  })
  const applyMutation = useMutation({
    mutationFn: () => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      if (!planId) throw new Error('Choose a Reading Plan before applying this list.')
      return customCBLApi.apply(selectedId, planId)
    },
    onSuccess: async (result) => {
      await applyCommittedReadingPlan(queryClient, result)
      onApplied?.(result)
      const added = result.added_issue_ids.length
      const skipped = result.skipped_existing_issue_ids.length
      setMessage(`Applied to Reading Plan: ${added} added${skipped ? `, ${skipped} already present` : ''}.`)
    },
  })
  const replaceMutation = useMutation({
    mutationFn: async ({
      issueIds: selectedIssueIds,
      confirmed,
    }: {
      issueIds: number[]
      confirmed: ReadingListPredecessorChange[] | null
    }) => {
      if (!selectedId || !persisted || !cblSource) {
        throw new Error('Choose a Reading List and a CBL source first.')
      }
      // Reject a stale review against the list the reader actually saw.
      const current = await customCBLApi.get(selectedId)
      if (replaceBaseline !== null && current.updated_at !== replaceBaseline) {
        throw new StaleReadingListReviewError()
      }
      const savedByIssue = new Map(persisted.entries.map((entry) => [entry.issue_id, entry]))
      const entryIntents: Record<number, ReadingListEntryIntent> = {}
      const checkpointIssueIds: number[] = []
      for (const issueId of selectedIssueIds) {
        const saved = savedByIssue.get(issueId)
        entryIntents[issueId] = { gate: saved?.gate ?? DEFAULT_GATE, skipped: saved?.skipped ?? false }
        if (saved?.is_checkpoint) checkpointIssueIds.push(issueId)
      }
      const undo = buildWritePayload(
        persisted.name,
        persisted.description ?? '',
        persisted.mode ?? DEFAULT_MODE,
        persisted.entries,
        null,
        checkpointTargetsFor(persisted.entries),
      )
      const payload: CustomCBLWrite = {
        name: name.trim(),
        description: description.trim() || null,
        mode,
        issue_ids: selectedIssueIds,
        entry_intents: entryIntents,
        checkpoint_issue_ids: checkpointIssueIds,
      }
      if (confirmed) payload.confirmed_predecessor_changes = confirmed
      const saved = await customCBLApi.update(selectedId, payload)
      return { saved, undo, sourceLabel: cblSource.name || cblSource.source_path }
    },
    onSuccess: async ({ saved, undo, sourceLabel }) => {
      await applyUpdatedCustomCBL(queryClient, saved)
      setEntries(normalizePositions(saved.entries))
      setMode(saved.mode ?? DEFAULT_MODE)
      setUndoPayload(undo)
      setUndoBaseline(saved.updated_at)
      setReplaceConfirmation(null)
      setReplaceOpen(false)
      setCblSource(null)
      setCblSubmittedQuery('')
      setCblQuery('')
      setReplaceError(null)
      setMessage(
        `Replaced this Reading List from ${sourceLabel}. Read history and ratings were not changed.`,
      )
    },
    onError: (error, variables) => {
      const detail = decodeCustomCBLError(error)
      if (
        detail.code === 'reading_list_predecessor_confirmation_required' &&
        detail.predecessorChanges.length > 0
      ) {
        setReplaceConfirmation({ issueIds: variables.issueIds, changes: detail.predecessorChanges })
        setReplaceError(null)
        return
      }
      setReplaceConfirmation(null)
      setReplaceError(
        messageFor(error, 'Unable to replace this Reading List from the chosen CBL.'),
      )
    },
  })
  const undoReplacementMutation = useMutation({
    mutationFn: async ({
      payload,
      confirmed,
    }: {
      payload: CustomCBLWrite
      confirmed: ReadingListPredecessorChange[] | null
    }) => {
      if (!selectedId) throw new Error('Choose a custom CBL first.')
      if (undoBaseline !== null) {
        const current = await customCBLApi.get(selectedId)
        if (current.updated_at !== undoBaseline) throw new StaleReadingListUndoError()
      }
      // Restoring a snapshot can re-change stored waits (for example, undoing a
      // confirmed strict reorder), so the same confirmation contract applies.
      const body: CustomCBLWrite = { ...payload }
      if (confirmed) body.confirmed_predecessor_changes = confirmed
      return customCBLApi.update(selectedId, body)
    },
    onSuccess: async (saved) => {
      await applyUpdatedCustomCBL(queryClient, saved)
      setEntries(normalizePositions(saved.entries))
      setMode(saved.mode ?? DEFAULT_MODE)
      setUndoPayload(null)
      setUndoBaseline(null)
      setUndoConfirmation(null)
      setReplaceError(null)
      setMessage('Restored the previous list membership and order. Read history and ratings were not changed.')
    },
    onError: (error) => {
      const detail = decodeCustomCBLError(error)
      if (
        detail.code === 'reading_list_predecessor_confirmation_required' &&
        detail.predecessorChanges.length > 0
      ) {
        // Keep the Undo snapshot so the reader can confirm this exact restore.
        setUndoConfirmation(detail.predecessorChanges)
        setReplaceError(null)
        return
      }
      if (error instanceof StaleReadingListUndoError) {
        setUndoPayload(null)
        setUndoBaseline(null)
      }
      setUndoConfirmation(null)
      setReplaceError(messageFor(error, 'Unable to undo this Reading List replacement.'))
    },
  })

  const isPending = createMutation.isPending || saveMutation.isPending || deleteMutation.isPending || applyMutation.isPending || replaceMutation.isPending || undoReplacementMutation.isPending
  useEffect(() => {
    onPendingChange?.(isPending)
    return () => onPendingChange?.(false)
  }, [isPending, onPendingChange])

  const persisted = detailQuery.data
  const dirty = useMemo(() => {
    if (!persisted) return false
    return (
      name.trim() !== persisted.name ||
      (description.trim() || '') !== (persisted.description ?? '') ||
      mode !== (persisted.mode ?? DEFAULT_MODE) ||
      !sameEntries(entries, persisted.entries)
    )
  }, [description, entries, mode, name, persisted])

  const entryNames = useMemo(() => {
    const names = new Map<number, string>()
    for (const entry of entries) names.set(entry.issue_id, `${entry.series_name} #${entry.issue_number}`)
    return names
  }, [entries])
  const nameFor = (issueId: number): string => entryNames.get(issueId) ?? `Issue #${issueId}`

  const requirements = useMemo(() => computeEntryRequirements(mode, entries), [mode, entries])

  const saveErrorDetail = useMemo(
    () => (saveMutation.error ? decodeCustomCBLError(saveMutation.error) : null),
    [saveMutation.error],
  )
  const createErrorDetail = useMemo(
    () => createMutation.error ? decodeCustomCBLError(createMutation.error) : null,
    [createMutation.error],
  )
  const createCycleError = createErrorDetail?.code === 'reading_list_cycle'
    ? describeCyclePath(createErrorDetail.cyclePath, () => 'An affected comic', 'create')
    : null
  const cycleEditorLinks = new Map<number, string>()
  if (createCycleError) {
    for (const edge of createErrorDetail?.cyclePath ?? []) {
      if (!edge.prerequisite_origin) continue
      if (edge.source_thread_id && edge.source_issue_name) cycleEditorLinks.set(edge.source_thread_id, edge.source_issue_name)
      if (edge.target_thread_id && edge.target_issue_name) cycleEditorLinks.set(edge.target_thread_id, edge.target_issue_name)
    }
  }
  const confirmationChanges =
    saveErrorDetail?.code === 'reading_list_predecessor_confirmation_required' &&
    saveErrorDetail.predecessorChanges.length > 0
      ? saveErrorDetail.predecessorChanges
      : null
  const cycleError = useMemo(() => {
    if (saveErrorDetail?.code !== 'reading_list_cycle') return null
    const resolveName = (issueId: number) => entryNames.get(issueId) ?? `Issue #${issueId}`
    return describeCyclePath(saveErrorDetail.cyclePath, resolveName)
  }, [entryNames, saveErrorDetail])

  const matchedEntries = useMemo(() => {
    const query = entrySearch.trim().toLocaleLowerCase()
    return entries.flatMap((entry, index) => {
      const label = `${entry.series_name} #${entry.issue_number}`
      return !query || label.toLocaleLowerCase().includes(query) ? [{ entry, index }] : []
    })
  }, [entries, entrySearch])
  const pageCount = Math.max(1, Math.ceil(matchedEntries.length / ENTRY_PAGE_SIZE))
  const currentPage = Math.min(entryPage, pageCount - 1)
  const visibleEntries = matchedEntries.slice(currentPage * ENTRY_PAGE_SIZE, (currentPage + 1) * ENTRY_PAGE_SIZE)

  const searchResults = (issueQuery.trim() === submittedIssueQuery ? issueSearchQuery.data ?? [] : []).filter(
    (candidate) => !entries.some((entry) => entry.issue_id === candidate.issue_id),
  )

  const create = (event: FormEvent) => {
    event.preventDefault()
    if (!newName.trim() || disabled || isPending) return
    setMessage(null)
    createMutation.mutate()
  }
  const search = (event: FormEvent) => {
    event.preventDefault()
    const next = issueQuery.trim()
    if (!next || disabled || isPending) return
    setSubmittedIssueQuery(next)
  }
  const addIssue = (candidate: CustomCBLIssueSearchResult) => {
    setEntries((current) => [...current, draftEntry(candidate, current.length)])
    setMessage(`Added ${candidate.series_name} #${candidate.issue_number} to this list. Save to keep your changes.`)
    setEntrySearch('')
    setEntryPage(Math.floor(entries.length / ENTRY_PAGE_SIZE))
    issueSearchInput.current?.focus()
  }
  const focusSearchResult = (event: KeyboardEvent<HTMLElement>, fromInput = false) => {
    const buttons = Array.from(issueSearchResults.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
    if (event.key === 'Escape' && !fromInput) {
      event.preventDefault()
      issueSearchInput.current?.focus()
      return
    }
    if (buttons.length === 0) return
    if (fromInput && event.key === 'Enter') {
      // Results already belong to this query: do not resubmit or add an
      // unintended issue. Enter adds only when a result button has focus.
      event.preventDefault()
      buttons[0].focus()
      return
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
    event.preventDefault()
    const current = event.target instanceof HTMLButtonElement ? buttons.indexOf(event.target) : -1
    const next = event.key === 'ArrowDown'
      ? (current + 1) % buttons.length
      : (current <= 0 ? buttons.length : current) - 1
    buttons[next].focus()
  }
  const removeIssue = (issueId: number) => {
    setEntries((current) => normalizePositions(current.filter((entry) => entry.issue_id !== issueId)))
    setMessage(null)
  }
  const moveIssue = (index: number, delta: -1 | 1) => {
    const target = index + delta
    if (target < 0 || target >= entries.length) return
    setEntries((current) => {
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return normalizePositions(next)
    })
    setMessage(null)
  }
  const moveIssueToPosition = (index: number, issueId: number) => {
    const position = Number(moveDestinations[issueId])
    if (!Number.isSafeInteger(position) || position < 1 || position > entries.length) return
    const target = position - 1
    if (index === target) return
    setEntries((current) => {
      const next = [...current]
      const [moved] = next.splice(index, 1)
      if (!moved) return current
      next.splice(target, 0, moved)
      return normalizePositions(next)
    })
    setEntrySearch('')
    setEntryPage(Math.floor(target / ENTRY_PAGE_SIZE))
    setExpandedEntryOptions(null)
    setMessage(null)
  }
  const jumpToPosition = () => {
    const position = Number(jumpPosition)
    if (!Number.isSafeInteger(position) || position < 1 || position > entries.length) return
    setEntrySearch('')
    setEntryPage(Math.floor((position - 1) / ENTRY_PAGE_SIZE))
  }
  const updateGate = (issueId: number, gate: ReadingListGate) => {
    setEntries((current) =>
      current.map((entry) => (entry.issue_id === issueId ? { ...entry, gate } : entry)),
    )
    setMessage(null)
  }
  const toggleSkipped = (issueId: number) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.issue_id === issueId ? { ...entry, skipped: !entry.skipped } : entry,
      ),
    )
    setMessage(null)
  }
  const toggleCheckpoint = (issueId: number) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.issue_id === issueId ? { ...entry, is_checkpoint: !entry.is_checkpoint } : entry,
      ),
    )
    setMessage(null)
  }
  const chooseList = (value: string) => {
    createMutation.reset()
    const next = value ? Number(value) : null
    if (next === selectedId) return
    // Saving can fail with a structured preview/cycle error tied to the list that
    // was submitted; switching lists must not carry that feedback onto another list.
    saveMutation.reset()
    deleteMutation.reset()
    setMessage(null)
    setConfirmDeleteOpen(false)
    setReplaceOpen(false)
    setCblSource(null)
    setCblSubmittedQuery('')
    setCblQuery('')
    setReplaceBaseline(null)
    setReplaceError(null)
    setReplaceConfirmation(null)
    setUndoConfirmation(null)
    setUndoPayload(null)
    setUndoBaseline(null)
    setSelectedId(next)
    setEntrySearch('')
    setEntryPage(0)
    setJumpPosition('')
    setExpandedEntryOptions(null)
    setMoveDestinations({})
  }
  const exportList = async () => {
    if (!selectedId || !persisted || dirty || disabled || isPending) return
    setExportError(null)
    let url: string | null = null
    let anchor: HTMLAnchorElement | null = null
    try {
      const xml = await customCBLApi.exportXml(selectedId)
      const blob = new Blob([xml], { type: 'application/xml' })
      url = URL.createObjectURL(blob)
      anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${persisted.name.replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '') || 'custom-reading-list'}.cbl`
      document.body.appendChild(anchor)
      anchor.click()
    } catch (caught) {
      setExportError(caught instanceof Error ? caught : new Error('Custom CBL export failed.'))
    } finally {
      anchor?.remove()
      if (url) URL.revokeObjectURL(url)
    }
  }

  const structuredSaveError = confirmationChanges !== null || cycleError !== null
  const error =
    exportError ??
    (createCycleError ? null : createMutation.error) ??
    deleteMutation.error ??
    applyMutation.error ??
    (structuredSaveError ? null : saveMutation.error) ??
    detailQuery.error ??
    listsQuery.error
  const errorText = error ? messageFor(error, 'Custom CBL operation failed.') : null
  const warnings = persisted?.warnings ?? []
  const replacement = useMemo(
    () =>
      persisted && cblPreviewQuery.data
        ? buildReplacementModel(persisted, cblPreviewQuery.data)
        : null,
    [persisted, cblPreviewQuery.data],
  )

  const searchCblSources = (event: FormEvent) => {
    event.preventDefault()
    if (disabled || isPending) return
    setCblSubmittedQuery(cblQuery.trim())
    setCblSource(null)
    setReplaceBaseline(null)
    setReplaceConfirmation(null)
    setReplaceError(null)
  }
  const chooseCblSource = (source: CBLSourceListDiscoveryItem) => {
    if (disabled || isPending) return
    const reload = cblSource?.id === source.id
    setCblSource(source)
    setReplaceBaseline(persisted?.updated_at ?? null)
    setReplaceConfirmation(null)
    setReplaceError(null)
    if (reload) void cblPreviewQuery.refetch()
  }
  const closeReplaceReview = () => {
    if (replaceMutation.isPending) return
    setReplaceOpen(false)
    setCblSource(null)
    setCblSubmittedQuery('')
    setCblQuery('')
    setReplaceBaseline(null)
    setReplaceConfirmation(null)
    setReplaceError(null)
  }
  const undoReplacement = () => {
    if (!undoPayload || isPending) return
    undoReplacementMutation.mutate({ payload: undoPayload, confirmed: null })
  }
  const confirmUndoReplacement = () => {
    const changes = undoConfirmation
    if (!undoPayload || !changes || undoReplacementMutation.isPending) return
    setUndoConfirmation(null)
    undoReplacementMutation.mutate({ payload: undoPayload, confirmed: changes })
  }

  return (
    <section className="rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3" aria-labelledby="custom-cbl-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 id="custom-cbl-heading" className="text-sm font-black text-[var(--theme-text-primary)]">Custom CBLs</h3>
          <p className="mt-1 text-xs text-[var(--theme-text-muted)]">Build one ordered list of real comics, choose a strict or loose reading order, add optional waits, and apply it to this Reading Plan.</p>
        </div>
        <button type="button" onClick={() => setOpen((value) => !value)} disabled={disabled || isPending} className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50" aria-expanded={open}>
          {open ? 'Close custom CBLs' : 'Create or edit custom CBL'}
        </button>
      </div>

      {open && (
        <div className="mt-4 space-y-4 border-t border-[var(--theme-border)] pt-4">
          <form onSubmit={create} className="flex flex-col gap-2 sm:flex-row">
            <input aria-label="New custom CBL name" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New custom CBL name" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
            <button type="submit" disabled={!newName.trim() || disabled || isPending} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">Create</button>
          </form>

          {(listsQuery.data?.length ?? 0) > 0 && (
            <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
              Custom CBL
              <select aria-label="Custom CBL" value={selectedId ?? ''} onChange={(event) => chooseList(event.target.value)} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50">
                <option value="">Choose a custom CBL</option>
                {(listsQuery.data ?? []).map((list) => <option key={list.id} value={list.id}>{list.name} · {list.issue_count} issues · {list.mode}</option>)}
              </select>
            </label>
          )}

          {selectedId && persisted && (
            <div className="space-y-4 rounded-xl border border-[var(--theme-border)] p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
                <label className="text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">Description<input value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} disabled={disabled || isPending} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm normal-case tracking-normal text-[var(--theme-text-primary)] disabled:opacity-50" /></label>
              </div>

              <fieldset disabled={disabled || isPending} className="rounded-xl border border-[var(--theme-border)] p-3">
                <legend className="px-1 text-sm font-medium text-[var(--theme-text-primary)]">List mode</legend>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="flex items-start gap-2 text-sm text-[var(--theme-text-primary)]">
                    <input type="radio" name={`custom-cbl-mode-${planId}`} value="strict" checked={mode === 'strict'} onChange={() => setMode('strict')} className="mt-1 h-4 w-4" />
                    <span>
                      <span className="font-bold">Strict</span>
                      <span className="block text-xs text-[var(--theme-text-muted)]">Every unread entry waits for all earlier entries, so only this list's first unread issue is available.</span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-sm text-[var(--theme-text-primary)]">
                    <input type="radio" name={`custom-cbl-mode-${planId}`} value="loose" checked={mode === 'loose'} onChange={() => setMode('loose')} className="mt-1 h-4 w-4" />
                    <span>
                      <span className="font-bold">Loose</span>
                      <span className="block text-xs text-[var(--theme-text-muted)]">Entries stand alone unless you add a wait. Placement never blocks progress in another series.</span>
                    </span>
                  </label>
                </div>
                {mode === 'strict' && (
                  <p className="mt-2 text-xs text-[var(--theme-text-muted)]">Strict lists warn when you leave out unread issues from a series you placed here; saving does not silently gate the omitted issues.</p>
                )}
              </fieldset>

              <form onSubmit={search} className="flex flex-col gap-2 sm:flex-row">
                <input ref={issueSearchInput} onKeyDown={(event) => focusSearchResult(event, true)} aria-describedby="custom-cbl-search-help" aria-label="Search issues for custom CBL" value={issueQuery} onChange={(event) => setIssueQuery(event.target.value)} placeholder="Search your issues, e.g. All-Star Comics" maxLength={200} disabled={disabled || isPending} className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50" />
                <button type="submit" disabled={!issueQuery.trim() || disabled || isPending || issueSearchQuery.isFetching} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">{issueSearchQuery.isFetching ? 'Searching…' : 'Find issues'}</button>
              </form>

              <p id="custom-cbl-search-help" className="text-xs text-[var(--theme-text-muted)]">Find issues, then use the arrow keys to choose a result and Enter to add it. Escape returns to search.</p>

              {searchResults.length > 0 && (
                <div ref={issueSearchResults} className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-[var(--theme-border)] p-2" aria-label="Custom CBL issue search results">
                  {searchResults.map((candidate) => (
                    <button key={candidate.issue_id} onKeyDown={(event) => focusSearchResult(event)} type="button" onClick={() => addIssue(candidate)} disabled={disabled || isPending} className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-2 text-left text-sm text-[var(--theme-text-primary)] hover:bg-white/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)] disabled:opacity-50">
                      <span>{candidate.series_name} #{candidate.issue_number}</span><span className="text-xs text-[var(--theme-text-dim)]">Add</span>
                    </button>
                  ))}
                </div>
              )}

              {entries.length > 0 && (
                <div className="surface-panel space-y-3 p-3" aria-label="Reading List navigation">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h4 className="text-sm font-bold text-[var(--theme-text-primary)]">Ordered issues ({entries.length})</h4>
                    <p className="text-xs text-[var(--theme-text-muted)]">Changes are saved with the list.</p>
                  </div>
                  <label className="block text-sm text-[var(--theme-text-primary)]">
                    Find an issue already in this list
                    <input
                      type="search"
                      aria-label="Find an issue in this reading list"
                      value={entrySearch}
                      onChange={(event) => { setEntrySearch(event.target.value); setEntryPage(0) }}
                      placeholder="Search titles or issue numbers"
                      className="mt-1 min-h-11 w-full rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)]"
                    />
                  </label>
                  <div className="flex flex-wrap items-end gap-2">
                    <label className="text-sm text-[var(--theme-text-primary)]">
                      Jump to position
                      <input
                        aria-label="Jump to reading list position"
                        type="number"
                        inputMode="numeric"
                        min={1}
                        max={entries.length}
                        value={jumpPosition}
                        onChange={(event) => setJumpPosition(event.target.value)}
                        className="mt-1 block min-h-11 w-28 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm"
                      />
                    </label>
                    <button type="button" disabled={!Number.isSafeInteger(Number(jumpPosition)) || Number(jumpPosition) < 1 || Number(jumpPosition) > entries.length} onClick={jumpToPosition} className="min-h-11 rounded-lg border border-[var(--theme-border)] px-4 text-sm font-semibold text-[var(--theme-text-primary)] disabled:opacity-40">Go to position</button>
                  </div>
                  <p aria-live="polite" className="text-xs text-[var(--theme-text-muted)]">
                    {matchedEntries.length} matching issues · Page {currentPage + 1} of {pageCount}
                  </p>
                  <div className="flex items-center justify-between gap-2">
                    <button type="button" onClick={() => setEntryPage((page) => Math.max(0, page - 1))} disabled={currentPage === 0} className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-sm font-semibold disabled:opacity-40">Previous 30</button>
                    <button type="button" onClick={() => setEntryPage((page) => Math.min(pageCount - 1, page + 1))} disabled={currentPage >= pageCount - 1} className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-sm font-semibold disabled:opacity-40">Next 30</button>
                  </div>
                </div>
              )}

              <ol className="space-y-2" aria-label="Custom CBL ordered issues">
                {visibleEntries.map(({ entry, index }) => (
                  <ReadingListEntryCard
                    key={entry.issue_id}
                    entry={entry}
                    index={index}
                    entryCount={entries.length}
                    mode={mode}
                    waitingOn={requirements.get(entry.issue_id) ?? []}
                    nameOf={nameFor}
                    expanded={expandedEntryOptions === entry.issue_id}
                    moveDestination={moveDestinations[entry.issue_id] ?? ''}
                    disabled={disabled || isPending}
                    onCheckpoint={() => toggleCheckpoint(entry.issue_id)}
                    onMoveEarlier={() => moveIssue(index, -1)}
                    onMoveLater={() => moveIssue(index, 1)}
                    onRemove={() => removeIssue(entry.issue_id)}
                    onToggleOptions={() => setExpandedEntryOptions((current) => current === entry.issue_id ? null : entry.issue_id)}
                    onGate={(gate) => updateGate(entry.issue_id, gate)}
                    onSkip={() => toggleSkipped(entry.issue_id)}
                    onDestinationChange={(value) => setMoveDestinations((current) => ({ ...current, [entry.issue_id]: value }))}
                    onMoveToPosition={() => moveIssueToPosition(index, entry.issue_id)}
                  />
                ))}
              </ol>
              {matchedEntries.length === 0 && entries.length > 0 && (
                <p className="text-sm text-[var(--theme-text-muted)]">No issues match this search. Clear the search to see the complete list.</p>
              )}
              {entries.length > ENTRY_PAGE_SIZE && (
                <div className="flex items-center justify-between gap-3">
                  <button type="button" onClick={() => setEntryPage((page) => Math.max(0, page - 1))} disabled={currentPage === 0} className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-sm disabled:opacity-40">Previous 30</button>
                  <button type="button" onClick={() => setEntryPage((page) => Math.min(pageCount - 1, page + 1))} disabled={currentPage >= pageCount - 1} className="min-h-11 rounded-lg border border-[var(--theme-border)] px-3 text-sm disabled:opacity-40">Next 30</button>
                </div>
              )}
              {entries.length === 0 && <p className="text-sm text-[var(--theme-text-muted)]">This custom CBL is empty. Search for issues above to build it.</p>}
              <p className="text-xs text-[var(--theme-text-muted)]">Skipping an issue here ignores it only in this list. It stays in your collection and other lists. Use your collection exclusions to remove a comic everywhere.</p>

              <button type="button" onClick={() => setReaderOpen((value) => !value)} aria-expanded={readerOpen} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-semibold text-[var(--theme-text-primary)]">{readerOpen ? 'Close list reader' : 'Read this list'}</button>
              {readerOpen && selectedId && <ReadingListReader key={selectedId} listId={selectedId} backTo={planId ? `/continuity-plans/${planId}` : `/reading-lists/${selectedId}`} />}

              <div className="space-y-3 rounded-xl border border-[var(--theme-border)] p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-[var(--theme-text-primary)]">Replace using CBL</h4>
                    <p className="mt-1 text-xs text-[var(--theme-text-muted)]">
                      Choose a global CBL, review exact before/after Issue IDs, then replace only this Reading List.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      if (replaceOpen) closeReplaceReview()
                      else setReplaceOpen(true)
                    }}
                    aria-expanded={replaceOpen}
                    disabled={disabled || isPending || dirty}
                    className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                  >
                    {replaceOpen ? 'Close replacement review' : 'Replace using CBL'}
                  </button>
                </div>

                {dirty && (
                  <p className="text-xs text-[var(--theme-warning)]">
                    Save or discard your unsaved edits before reviewing a replacement.
                  </p>
                )}

                {replaceOpen && (
                  <div className="space-y-3 border-t border-[var(--theme-border)] pt-3">
                    <form onSubmit={searchCblSources} className="flex flex-col gap-2 sm:flex-row">
                      <input
                        aria-label="Search global CBL sources"
                        value={cblQuery}
                        onChange={(event) => setCblQuery(event.target.value)}
                        placeholder="Search global CBL sources"
                        maxLength={200}
                        disabled={disabled || isPending}
                        className="min-h-11 flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-sm text-[var(--theme-text-primary)] disabled:opacity-50"
                      />
                      <button
                        type="submit"
                        disabled={!cblQuery.trim() || disabled || isPending || cblSourcesQuery.isFetching}
                        className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                      >
                        {cblSourcesQuery.isFetching ? 'Searching…' : 'Find CBLs'}
                      </button>
                    </form>

                    {cblSourcesQuery.isError && (
                      <div className="space-y-2 rounded-xl border border-[var(--theme-border)] p-3">
                        <p role="alert" className="text-sm text-[var(--theme-danger)]">
                          {messageFor(cblSourcesQuery.error, 'Unable to search global CBL sources.')}
                        </p>
                        <button
                          type="button"
                          onClick={() => void cblSourcesQuery.refetch()}
                          disabled={disabled || isPending}
                          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                        >
                          Retry source search
                        </button>
                      </div>
                    )}

                    {(cblSourcesQuery.data?.length ?? 0) > 0 && (
                      <div className="grid gap-2" aria-label="Global CBL source candidates">
                        {(cblSourcesQuery.data ?? []).map((source) => (
                          <button
                            key={source.id}
                            type="button"
                            onClick={() => chooseCblSource(source)}
                            disabled={disabled || isPending}
                            className={`rounded-xl border p-3 text-left disabled:opacity-50 ${
                              cblSource?.id === source.id
                                ? 'border-[var(--theme-continuity-accent)]'
                                : 'border-[var(--theme-border)]'
                            } hover:bg-white/5`}
                          >
                            <span className="block text-sm font-bold text-[var(--theme-text-primary)]">
                              {source.name || source.source_path}
                            </span>
                            <span className="mt-1 block text-xs text-[var(--theme-text-dim)]">
                              {source.declared_issue_count !== null
                                ? `${source.declared_issue_count} source entries`
                                : 'Source entries unavailable'}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}

                    {cblSource && cblPreviewQuery.isPending && (
                      <p role="status" className="text-sm text-[var(--theme-text-muted)]">
                        Reconciling the chosen CBL against this list…
                      </p>
                    )}

                    {cblSource && cblPreviewQuery.isError && (
                      <div className="space-y-2 rounded-xl border border-[var(--theme-border)] p-3">
                        <p role="alert" className="text-sm text-[var(--theme-danger)]">
                          {messageFor(cblPreviewQuery.error, 'Unable to preview the chosen CBL source.')}
                        </p>
                        <button
                          type="button"
                          onClick={() => void cblPreviewQuery.refetch()}
                          disabled={disabled || isPending}
                          className="min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                        >
                          Retry preview
                        </button>
                      </div>
                    )}

                    {replacement && cblSource && (
                      <>
                        {replacement.unresolvedCount > 0 && (
                          <p className="text-xs text-[var(--theme-warning)]">
                            {replacement.unresolvedCount} source {replacement.unresolvedCount === 1 ? 'entry is' : 'entries are'} not in your library yet and cannot join a Reading List until resolved. They are left out of this review.
                          </p>
                        )}
                        <CblReplaceReviewPanel
                          key={`${cblSource.id}-${replacement.after.map((entry) => entry.comicId).join(',')}`}
                          listName={persisted.name}
                          listId={persisted.id}
                          mode={mode}
                          before={replacement.before}
                          after={replacement.after}
                          onConfirm={(selectedIssueIds) =>
                            replaceMutation.mutate({ issueIds: selectedIssueIds, confirmed: null })
                          }
                          onCancel={closeReplaceReview}
                          onUndo={undoPayload ? undoReplacement : undefined}
                        />
                      </>
                    )}

                    {replaceError && (
                      <p role="alert" className="text-sm text-[var(--theme-danger)]">
                        {replaceError}
                      </p>
                    )}
                  </div>
                )}

                {undoPayload && !replaceOpen && (
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={undoReplacement}
                      disabled={disabled || isPending || dirty}
                      className="min-h-10 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-primary)] disabled:opacity-50"
                    >
                      {undoReplacementMutation.isPending ? 'Undoing…' : 'Undo last replacement'}
                    </button>
                    <span className="text-xs text-[var(--theme-text-muted)]">
                      Restores list membership and order only; read history and ratings stay.
                    </span>
                  </div>
                )}
                {replaceError && !replaceOpen && (
                  <p role="alert" className="text-sm text-[var(--theme-danger)]">
                    {replaceError}
                  </p>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => saveMutation.mutate(null)} disabled={!dirty || !name.trim() || disabled || isPending} className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50">{saveMutation.isPending ? 'Saving…' : 'Save custom CBL'}</button>
                {planId && (<button type="button" onClick={() => applyMutation.mutate()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-continuity-accent)] px-4 text-sm font-black text-[var(--theme-continuity-accent)] disabled:opacity-50">{applyMutation.isPending ? 'Applying…' : 'Apply to this Reading Plan'}</button>)}
                <button type="button" onClick={() => void exportList()} disabled={dirty || entries.length === 0 || disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Export .cbl</button>
                <button type="button" onClick={() => { deleteMutation.reset(); setConfirmDeleteOpen(true) }} disabled={disabled || isPending} className="min-h-11 rounded-xl border border-[var(--theme-danger)] px-4 text-sm font-bold text-[var(--theme-danger)] disabled:opacity-50">Delete</button>
              </div>
              {dirty && <p className="text-xs text-[var(--theme-warning)]">Save this custom CBL before applying or exporting it.</p>}
            </div>
          )}

          {warnings.length > 0 && (
            <div className="rounded-xl border border-[var(--theme-warning)]/60 p-3" aria-live="polite">
              <p className="text-xs font-bold uppercase tracking-wider text-[var(--theme-warning)]">Coverage warnings</p>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-[var(--theme-text-muted)]" aria-label="Strict list coverage warnings">
                {warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
          {createCycleError && (
            <div role="alert" className="space-y-2 text-sm text-[var(--theme-error)]">
              <p>{createCycleError}</p>
              {cycleEditorLinks.size > 0 && (
                <ul className="space-y-1">
                  {[...cycleEditorLinks].map(([threadId, issueName]) => (
                    <li key={threadId}><Link className="text-[var(--theme-continuity-accent)] underline" to={`/thread/${threadId}?prerequisites=1`}>Review prerequisites for {issueName}</Link></li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {cycleError && <p role="alert" className="text-sm text-[var(--theme-warning)]">{cycleError}</p>}
          {message && <p role="status" className="text-sm text-emerald-300">{message}</p>}
          {errorText && <p role="alert" className="text-sm text-red-300">{errorText}</p>}
        </div>
      )}

      <ConfirmDialog
        isOpen={confirmDeleteOpen && Boolean(persisted)}
        title="Delete custom CBL"
        isPending={deleteMutation.isPending}
        error={deleteMutation.error ? messageFor(deleteMutation.error, 'Unable to delete this Reading List.') : null}
        confirmLabel="Delete custom CBL"
        pendingLabel="Deleting…"
        onConfirm={() => { if (selectedId) deleteMutation.mutate(selectedId) }}
        onCancel={() => { if (!deleteMutation.isPending) { deleteMutation.reset() } setConfirmDeleteOpen(false) }}
        testId="delete-custom-cbl-dialog"
      >
        <p className="text-sm text-[var(--theme-text-muted)]">
          Permanently delete <span className="font-bold text-[var(--theme-text-primary)]">{persisted?.name}</span>?
        </p>
        <p className="text-sm text-[var(--theme-text-muted)]">
          This removes the Reading List together with its entries and reading order. Read history
          and ratings for those comics are not changed.
        </p>
      </ConfirmDialog>
      <Modal
        isOpen={confirmationChanges !== null}
        title="Confirm waiting changes"
        onClose={() => saveMutation.reset()}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            This edit changes which issues wait on which. Review the new waits, then confirm to save. Cancel keeps the saved list exactly as it is.
          </p>
          <ul className="space-y-2" aria-label="Waiting changes">
            {(confirmationChanges ?? []).map((change) => (
              <li key={change.issue_id} className="rounded-xl border border-[var(--theme-border)] p-3 text-sm text-[var(--theme-text-primary)]">
                {describePredecessorChange(change)}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => saveMutation.reset()} disabled={saveMutation.isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Cancel</button>
            <button
              type="button"
              onClick={() => saveMutation.mutate(saveErrorDetail?.predecessorChanges ?? null)}
              disabled={saveMutation.isPending}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {saveMutation.isPending ? 'Saving…' : 'Confirm and save'}
            </button>
          </div>
        </div>
      </Modal>
      <Modal
        isOpen={replaceConfirmation !== null}
        title="Confirm replacement waiting changes"
        onClose={() => setReplaceConfirmation(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Replacing this Reading List changes which issues wait on which. Review the new waits, then confirm the same replacement review. Cancel leaves the saved list exactly as it is.
          </p>
          <ul className="space-y-2" aria-label="Replacement waiting changes">
            {(replaceConfirmation?.changes ?? []).map((change) => (
              <li key={change.issue_id} className="rounded-xl border border-[var(--theme-border)] p-3 text-sm text-[var(--theme-text-primary)]">
                {describePredecessorChange(change)}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => setReplaceConfirmation(null)} disabled={replaceMutation.isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Cancel</button>
            <button
              type="button"
              onClick={() => {
                const pending = replaceConfirmation
                if (!pending) return
                setReplaceConfirmation(null)
                replaceMutation.mutate({ issueIds: pending.issueIds, confirmed: pending.changes })
              }}
              disabled={replaceMutation.isPending}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {replaceMutation.isPending ? 'Replacing…' : 'Confirm and replace'}
            </button>
          </div>
        </div>
      </Modal>
      <Modal
        isOpen={undoConfirmation !== null}
        title="Confirm undo waiting changes"
        onClose={() => setUndoConfirmation(null)}
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--theme-text-muted)]">
            Restoring the previous list changes which issues wait on which. Review the restored waits, then confirm. Cancel keeps the replaced list exactly as it is.
          </p>
          <ul className="space-y-2" aria-label="Undo waiting changes">
            {(undoConfirmation ?? []).map((change) => (
              <li key={change.issue_id} className="rounded-xl border border-[var(--theme-border)] p-3 text-sm text-[var(--theme-text-primary)]">
                {describePredecessorChange(change)}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={() => setUndoConfirmation(null)} disabled={undoReplacementMutation.isPending} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-4 text-sm font-bold text-[var(--theme-text-primary)] disabled:opacity-50">Cancel</button>
            <button
              type="button"
              onClick={confirmUndoReplacement}
              disabled={undoReplacementMutation.isPending}
              className="min-h-11 rounded-xl bg-[var(--theme-continuity-accent)] px-4 text-sm font-black text-black disabled:opacity-50"
            >
              {undoReplacementMutation.isPending ? 'Restoring…' : 'Confirm and restore'}
            </button>
          </div>
        </div>
      </Modal>
    </section>
  )
}
