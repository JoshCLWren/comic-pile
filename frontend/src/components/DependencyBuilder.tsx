import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import Modal from './Modal'
import DependencyFlowchart from './DependencyFlowchart'
import ReadingOrderTimeline from './ReadingOrderTimeline'
import DependencyCrossoverControls from './DependencyCrossoverControls'
import {
  useThreadDependencies,
  useBlockedThreadIds,
  useSearchThreads,
  useThreadIssuesForDependency,
  useCreateDependency,
  useDeleteDependency,
  useUpdateDependency,
  useMigrateThread,
} from '../hooks'
import { threadsApi } from '../services/api-threads'
import { dependenciesApi } from '../services/api'
import type { Dependency, FlowchartDependency, FlowchartNode, Issue, Thread, ThreadDependenciesResponse } from '../types'
import { buildFlowchartGraph } from '../utils/dependencyFlowchartAdapter'
import { getApiErrorDetail } from '../utils/apiError'
import { useToast } from '../contexts/useToast'

function groupByThread(deps: Dependency[], labelKey: 'source_label' | 'target_label'): Map<string, Dependency[]> {
  const groups = new Map<string, Dependency[]>()
  for (const dep of deps) {
    const label = dep[labelKey] ?? 'Unknown'
    const threadName = dep.is_issue_level ? label.replace(/ #\d+$/, '') : label
    const existing = groups.get(threadName) ?? []
    existing.push(dep)
    groups.set(threadName, existing)
  }
  return groups
}

interface DependencyBuilderProps {
  thread: Thread | null
  isOpen: boolean
  onClose: () => void
  onChanged?: () => void
}

export default function DependencyBuilder({
  thread,
  isOpen,
  onClose,
  onChanged,
}: DependencyBuilderProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [showReadingOrder, setShowReadingOrder] = useState(false)
  const [readingView, setReadingView] = useState<'timeline' | 'graph'>('timeline')
  const [sourceIssueId, setSourceIssueId] = useState<number | null>(null)
  const [targetIssueId, setTargetIssueId] = useState<number | null>(null)
  // Inline migration state
  const [showInlineMigration, setShowInlineMigration] = useState(false)
  const [migrationLastRead, setMigrationLastRead] = useState('')
  const [migrationTotal, setMigrationTotal] = useState('')
  // Undo state for dependency deletion
  const [pendingDeletion, setPendingDeletion] = useState<{
    dependencyId: number
    dependencyData: Dependency
    timeoutId: ReturnType<typeof setTimeout>
    toastId: string
  } | null>(null)
  const toast = useToast()
  // Note editing state
  const [editingNoteId, setEditingNoteId] = useState<number | null>(null)
  const [noteText, setNoteText] = useState('')
  const [error, setError] = useState('')

  const threadId = thread?.id ?? undefined

  const {
    data: dependenciesData,
    isPending: isLoadingDeps,
    error: depsError,
    refetch: refetchDependencies,
  } = useThreadDependencies(threadId, isOpen)

  const { data: blockedIdsData } = useBlockedThreadIds(isOpen && showReadingOrder)

  const {
    data: searchResultsData,
    isPending: isSearching,
    error: searchError,
  } = useSearchThreads(searchQuery, isOpen)

  const searchResults = useMemo(
    () => (searchResultsData?.threads ?? []).filter((candidate) => candidate.id !== threadId),
    [searchResultsData, threadId]
  )

  const selectedThread = useMemo(
    () => searchResults.find((candidate) => candidate.id === selectedThreadId) || null,
    [searchResults, selectedThreadId]
  )

  const selectedThreadNeedsMigration = useMemo(() => {
    if (!selectedThread) return false
    return selectedThread.total_issues === null || selectedThread.total_issues === undefined
  }, [selectedThread])

  const issuesEnabled = isOpen && selectedThreadId != null && !selectedThreadNeedsMigration

  const {
    data: sourceIssues,
    isPending: isLoadingSourceIssues,
    error: sourceIssuesError,
  } = useThreadIssuesForDependency(selectedThreadId, issuesEnabled)

  const {
    data: targetIssues,
    isPending: isLoadingTargetIssues,
    error: targetIssuesError,
  } = useThreadIssuesForDependency(threadId, issuesEnabled)

  const createDependencyMutation = useCreateDependency(threadId)
  const deleteDependencyMutation = useDeleteDependency(threadId)
  const updateDependencyMutation = useUpdateDependency(threadId)
  const migrateThreadMutation = useMigrateThread()

  const dependencies = useMemo(
    () => dependenciesData ?? { blocking: [], blocked_by: [] },
    [dependenciesData]
  )

  const blockedIds = useMemo(
    () => new Set(blockedIdsData ?? []),
    [blockedIdsData]
  )

  const isSaving = createDependencyMutation.isPending
  const isMigrating = migrateThreadMutation.isPending
  const isSavingNote = updateDependencyMutation.isPending

  // Flowchart state
  const [isGraphLoading, setIsGraphLoading] = useState(false)
  const [flowchartThreads, setFlowchartThreads] = useState<Thread[]>([])
  const [flowchartDependencies, setFlowchartDependencies] = useState<FlowchartDependency[]>([])
  const [flowchartIssueNodes, setFlowchartIssueNodes] = useState<FlowchartNode[]>([])

  const loadFlowchartData = useCallback(async () => {
    if (!threadId) return
    setIsGraphLoading(true)
    try {
      const depsData = await dependenciesApi.listThreadDependencies(threadId)

      const allDeps = [...depsData.blocking, ...depsData.blocked_by]
      const graph = buildFlowchartGraph(allDeps, threadId)
      const relatedIds = graph.relatedThreadIds
      const allEdges = graph.edges

      const allThreads = await threadsApi.list()
      const relatedThreads = allThreads.threads.filter((t) => relatedIds.has(t.id))

      setFlowchartThreads(relatedThreads)
      setFlowchartDependencies(allEdges)
      setFlowchartIssueNodes(graph.issueNodes)
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setIsGraphLoading(false)
    }
  }, [threadId])

  useEffect(() => {
    if (pendingDeletion) {
      clearTimeout(pendingDeletion.timeoutId)
      dependenciesApi.deleteDependency(pendingDeletion.dependencyId)
        .then(() => {
          onChanged?.()
        })
        .catch((deleteError: unknown) => {
          setError(getApiErrorDetail(deleteError))
        })
        .finally(() => {
          toast.removeToast(pendingDeletion.toastId)
          setPendingDeletion(null)
        })
    }

    if (!isOpen || !threadId) return
    setSearchQuery('')
    setSelectedThreadId(null)
    setError('')
    setShowReadingOrder(false)
    setReadingView('timeline')
    setSourceIssueId(null)
    setTargetIssueId(null)
    setShowInlineMigration(false)

    refetchDependencies()
  }, [isOpen, threadId, refetchDependencies, onChanged, pendingDeletion, toast])

  useEffect(() => {
    if (sourceIssuesError) {
      setError(getApiErrorDetail(sourceIssuesError))
    }
    if (targetIssuesError) {
      setError(getApiErrorDetail(targetIssuesError))
    }
    if (depsError) {
      setError(getApiErrorDetail(depsError))
    }
    if (searchError) {
      setError(getApiErrorDetail(searchError))
    }
  }, [sourceIssuesError, targetIssuesError, depsError, searchError])

  // Preserve the legacy default of selecting the first loaded prerequisite and
  // target issue once issue-level tracking is available, without clobbering an
  // explicit user selection when the loaded issue lists change.
  useEffect(() => {
    if (!isOpen || !selectedThread || selectedThreadNeedsMigration) return
    const selectFirst = (current: number | null, issues: Issue[] | undefined): number | null => {
      if (current != null && issues?.some((issue) => issue.id === current)) return current
      return issues?.[0]?.id ?? null
    }
    setSourceIssueId((current) => selectFirst(current, sourceIssues))
    setTargetIssueId((current) => selectFirst(current, targetIssues))
  }, [isOpen, selectedThread, selectedThreadNeedsMigration, sourceIssues, targetIssues])

  function isDuplicateDependency(): boolean {
    if (!threadId || !selectedThreadId) return false
    if (!sourceIssueId || !targetIssueId) return false
    return (
      dependencies.blocking.some(
        (dep) => dep.source_issue_id === sourceIssueId && dep.target_issue_id === targetIssueId
      ) ||
      dependencies.blocked_by.some(
        (dep) => dep.source_issue_id === sourceIssueId && dep.target_issue_id === targetIssueId
      )
    )
  }

  async function handleInlineMigration(e: FormEvent) {
    e.preventDefault()
    if (!migrationLastRead.trim() || !migrationTotal.trim()) {
      setError('Both fields are required for migration.')
      return
    }
    const lastRead = Number(migrationLastRead)
    const total = Number(migrationTotal)
    if (
      Number.isNaN(lastRead) ||
      Number.isNaN(total) ||
      !Number.isInteger(lastRead) ||
      !Number.isInteger(total) ||
      total < 1 ||
      lastRead < 0 ||
      lastRead > total
    ) {
      setError('Invalid migration values. Both must be whole numbers and last read must be 0-total.')
      return
    }

    setError('')
    try {
      await migrateThreadMutation.mutateAsync({
        threadId: selectedThreadId!,
        lastIssueRead: lastRead,
        totalIssues: total,
      })
      setShowInlineMigration(false)
      setMigrationLastRead('')
      setMigrationTotal('')
    } catch (migrationError: unknown) {
      setError(getApiErrorDetail(migrationError))
    }
  }

  async function handleCreateDependency() {
    if (!threadId || !selectedThreadId || !thread) return

    const targetHasIssueTracking = thread.total_issues !== null && thread.total_issues !== undefined
    if (!targetHasIssueTracking) {
      setError('Target series must be migrated to issue tracking before adding issue dependencies.')
      return
    }

    if (!sourceIssueId || !targetIssueId) {
      setError('Both prerequisite issue and target issue must be selected.')
      return
    }

    setError('')
    try {
      const result = await createDependencyMutation.mutateAsync({
        sourceType: 'issue',
        sourceId: sourceIssueId,
        targetType: 'issue',
        targetId: targetIssueId,
      })
      if (result.warning) {
        toast.showToast(result.warning, 'warning')
      }
      setSearchQuery('')
      setSelectedThreadId(null)
      setSourceIssueId(null)
      setTargetIssueId(null)
      // Refresh is covered by useCreateDependency's
      // invalidateAfterDependencyChange; no manual refetch loop.
      onChanged?.()
    } catch (saveError: unknown) {
      setError(getApiErrorDetail(saveError))
    }
  }

  async function handleDeleteDependency(dependencyId: number) {
    setError('')
    try {
      const dependencyToDelete = [...dependencies.blocking, ...dependencies.blocked_by].find(
        (dep) => dep.id === dependencyId
      )

      if (!dependencyToDelete) return

      const message = dependencyToDelete.source_label && dependencyToDelete.target_label
        ? `${dependencyToDelete.source_label} → ${dependencyToDelete.target_label}`
        : `Dependency #${dependencyId}`

      const timeoutId = setTimeout(async () => {
        try {
          await deleteDependencyMutation.mutateAsync(dependencyId)
          setPendingDeletion(null)
          // Refresh is covered by useDeleteDependency's
          // invalidateAfterDependencyChange; no manual refetch loop.
          onChanged?.()
        } catch (deleteError: unknown) {
          setError(getApiErrorDetail(deleteError))
        }
      }, 5000)

      const toastId = toast.showToast(
        `${message} removed.`,
        'info',
        {
          label: 'Undo',
          onClick: () => {
            clearTimeout(timeoutId)
            setPendingDeletion(null)
            toast.removeToast(toastId)
          }
        }
      )

      setPendingDeletion({
        dependencyId,
        dependencyData: dependencyToDelete,
        timeoutId,
        toastId,
      })
    } catch (deleteError: unknown) {
      setError(getApiErrorDetail(deleteError))
    }
  }

  async function handleSaveNote(dependencyId: number) {
    setError('')
    try {
      await updateDependencyMutation.mutateAsync({
        dependencyId,
        note: noteText.trim() || null,
      })
      setEditingNoteId(null)
      setNoteText('')
    } catch (saveError: unknown) {
      setError(getApiErrorDetail(saveError))
    }
  }

  function handleStartEditNote(dep: Dependency) {
    setEditingNoteId(dep.id)
    setNoteText(dep.note ?? '')
  }

  function handleCancelEditNote() {
    setEditingNoteId(null)
    setNoteText('')
  }

  const refreshGraphData = useCallback(async () => {
    await loadFlowchartData()
  }, [loadFlowchartData])

  async function handleToggleReadingOrder() {
    const willShowReadingOrder = !showReadingOrder
    setShowReadingOrder(willShowReadingOrder)
    setReadingView('timeline')
    if (willShowReadingOrder) {
      await refreshGraphData()
    }
  }

  async function handleSelectReadingView(view: 'timeline' | 'graph') {
    setReadingView(view)
    if (view === 'graph') {
      await refreshGraphData()
    }
  }

  return (
    <Modal isOpen={isOpen} title={`Dependencies: ${thread?.title || ''}`} onClose={onClose} autoFocus={false}>
      <div className="space-y-4">
      {/* Flowchart toggle */}
      {thread && (dependencies.blocking.length > 0 || dependencies.blocked_by.length > 0) && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleToggleReadingOrder}
            className="w-full py-3 rounded-lg border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] transition-colors"
            data-testid="toggle-reading-order"
          >
            {showReadingOrder ? '▲ Hide Reading Order' : '▼ View Reading Order'}
          </button>

            {showReadingOrder && (
              <div className="space-y-3 rounded-3xl border border-white/10 bg-black/20 p-3">
                <div
                  className="flex gap-2 text-[11px] font-black uppercase tracking-widest"
                  role="tablist"
                  aria-label="Reading order view"
                  onKeyDown={(e) => {
                    const tabs = Array.from(e.currentTarget.querySelectorAll('[role="tab"]')) as HTMLElement[];
                    const currentIndex = tabs.indexOf(document.activeElement as HTMLElement);
                    if (currentIndex === -1) return;
                    let newIndex = currentIndex;
                    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                      e.preventDefault();
                      newIndex = (currentIndex + 1) % tabs.length;
                    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                      e.preventDefault();
                      newIndex = (currentIndex - 1 + tabs.length) % tabs.length;
                    } else if (e.key === 'Home') {
                      e.preventDefault();
                      newIndex = 0;
                    } else if (e.key === 'End') {
                      e.preventDefault();
                      newIndex = tabs.length - 1;
                    }
                    if (newIndex !== currentIndex) {
                      tabs[newIndex]?.focus();
                    }
                  }}
                >
                  <button
                    type="button"
                    role="tab"
                    id="reading-order-timeline-tab"
                    aria-selected={readingView === 'timeline'}
                    aria-controls="timeline-panel"
                    onClick={() => handleSelectReadingView('timeline')}
                    className={`flex-1 rounded-2xl border px-3 py-3 ${
                      readingView === 'timeline'
                        ? 'border-white text-white'
                        : 'border-white/20 text-stone-400'
                    }`}
                  >
                    Timeline
                  </button>
                  <button
                    type="button"
                    role="tab"
                    id="reading-order-flowchart-tab"
                    aria-selected={readingView === 'graph'}
                    aria-controls="flowchart-panel"
                    onClick={() => handleSelectReadingView('graph')}
                    className={`flex-1 rounded-2xl border px-3 py-3 ${
                      readingView === 'graph'
                        ? 'border-white text-white'
                        : 'border-white/20 text-stone-400'
                    }`}
                  >
                    Flowchart
                  </button>
                </div>

                <div className="min-h-[200px]">
                  <div
                    role="tabpanel"
                    id="timeline-panel"
                    aria-labelledby="reading-order-timeline-tab"
                    hidden={readingView !== 'timeline'}
                  >
                    <ReadingOrderTimeline thread={thread} dependencies={[...dependencies.blocking, ...dependencies.blocked_by]} />
                  </div>
                  <div
                    role="tabpanel"
                    id="flowchart-panel"
                    aria-labelledby="reading-order-flowchart-tab"
                    hidden={readingView !== 'graph'}
                  >
                    {isGraphLoading ? (
                      <p className="text-center text-xs text-stone-400">Loading flowchart…</p>
                    ) : (
                      <DependencyFlowchart
                        threads={flowchartThreads}
                        dependencies={flowchartDependencies}
                        blockedIds={blockedIds}
                        issueNodes={flowchartIssueNodes}
                      />
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Dependency type
          </p>
          <p className="text-xs text-stone-500">
            Issue-level: blocks only when the target issue becomes next unread.
          </p>
        </div>

        <div className="space-y-2">
          <label htmlFor="search-prereq-thread" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Search prerequisite series
          </label>
          <input
            id="search-prereq-thread"
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Type at least 2 characters"
            className="w-full rounded-xl px-3 py-2 text-sm form-control"
          />
          {isSearching && <p className="text-xs text-stone-500">Searching…</p>}
          {!isSearching && searchQuery.trim().length >= 2 && searchResults.length === 0 && (
            <p className="text-xs text-stone-500">No matching series found.</p>
          )}
          {searchResults.length > 0 && (
            <div className="max-h-40 overflow-auto border border-white/10 rounded-xl bg-white/5">
              {searchResults.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  onClick={() => setSelectedThreadId(candidate.id)}
                  className={`w-full text-left px-3 py-2 text-sm border-b last:border-b-0 border-white/5 hover:bg-white/10 ${
                    selectedThreadId === candidate.id ? 'bg-white/10 text-white' : 'text-stone-300'
                  }`}
                >
                  {candidate.title} <span className="text-xs text-stone-500">({candidate.format})</span>
                </button>
              ))}
            </div>
          )}

          {/* Inline migration prompt */}
           {selectedThread && selectedThreadNeedsMigration && (
             <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3 space-y-2">
               <p className="text-xs text-amber-300 font-bold">
                 {selectedThread.title} isn&apos;t tracking issues yet.
               </p>
               {!showInlineMigration ? (
                 <button
                   type="button"
                   onClick={() => setShowInlineMigration(true)}
                   className="text-xs font-black uppercase tracking-widest text-amber-200 hover:text-amber-100"
                 >
                   Migrate Now
                 </button>
                ) : (
                  <form onSubmit={handleInlineMigration} className="space-y-2">
                    <div className="flex flex-col md:flex-row gap-2">
                      <div className="flex-1">
                        <label htmlFor="migration-last-read" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Last issue read</label>
                        <input
                          id="migration-last-read"
                          type="number"
                          min="0"
                          value={migrationLastRead}
                          onChange={(e) => setMigrationLastRead(e.target.value)}
                          className="w-full rounded-lg px-2 py-1 text-sm form-control"
                          required
                        />
                      </div>
                      <div className="flex-1">
                        <label htmlFor="migration-total" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Total issues</label>
                        <input
                          id="migration-total"
                          type="number"
                          min="1"
                          value={migrationTotal}
                          onChange={(e) => setMigrationTotal(e.target.value)}
                          className="w-full rounded-lg px-2 py-1 text-sm form-control"
                          required
                        />
                      </div>
                    </div>
                    <button
                      type="submit"
                      disabled={isMigrating}
                      className="w-full py-1.5 bg-amber-500/20 border border-amber-500/30 rounded-lg text-xs font-black uppercase tracking-widest text-amber-200 disabled:opacity-50"
                    >
                      {isMigrating ? 'Migrating…' : 'Migrate'}
                    </button>
                  </form>
               )}
             </div>
           )}

           {selectedThread && !selectedThreadNeedsMigration && (
             <div className="space-y-2">
               {(isLoadingSourceIssues || isLoadingTargetIssues) ? (
                 <p className="text-xs text-stone-500">Loading issues…</p>
               ) : (
                 <div className="flex flex-col md:flex-row gap-2 min-w-0">
                   <div className="min-w-0 w-full">
                     <label htmlFor="source-issue" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                       Prerequisite issue
                     </label>
                     <select
                       id="source-issue"
                        value={sourceIssueId || ''}
                        onChange={(event) => setSourceIssueId(event.target.value ? Number(event.target.value) : null)}
                        className="w-full rounded-xl px-3 py-2 text-sm form-control"
                        disabled={(sourceIssues?.length ?? 0) === 0}
                      >
                        {(sourceIssues?.length ?? 0) === 0 ? (
                          <option value="">No unread issues available</option>
                        ) : (
                          <>
                            <option value="">Select an issue</option>
                            {sourceIssues!.map((issue) => (
                              <option key={issue.id} value={issue.id}>
                                #{issue.issue_number}
                              </option>
                            ))}
                          </>
                        )}
                      </select>
                    </div>
                    <div className="min-w-0 w-full">
                      <label htmlFor="target-issue" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                        Target issue
                      </label>
                      <select
                        id="target-issue"
                        value={targetIssueId || ''}
                        onChange={(event) => setTargetIssueId(event.target.value ? Number(event.target.value) : null)}
                        className="w-full rounded-xl px-3 py-2 text-sm form-control"
                        disabled={(targetIssues?.length ?? 0) === 0}
                      >
                        {(targetIssues?.length ?? 0) === 0 ? (
                          <option value="">No unread issues available</option>
                        ) : (
                          <>
                            <option value="">Select an issue</option>
                            {targetIssues!.map((issue) => (
                              <option key={issue.id} value={issue.id}>
                                #{issue.issue_number}
                              </option>
                            ))}
                          </>
                        )}
                      </select>
                    </div>
                 </div>
               )}
             </div>
           )}

           {selectedThread && !selectedThreadNeedsMigration && (
             <DependencyCrossoverControls
               sourceIssueId={sourceIssueId}
               targetIssueId={targetIssueId}
               disabled={isLoadingSourceIssues || isLoadingTargetIssues}
               onMembershipChanged={onChanged}
             />
            )}

            <button
              type="button"
              onClick={handleCreateDependency}
              disabled={
                !selectedThread || selectedThreadNeedsMigration || !sourceIssueId || !targetIssueId || isSaving || isDuplicateDependency()
              }
              className="w-full py-2 rounded-xl bg-[var(--theme-primary-action)] font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-50 whitespace-normal break-words text-left"
            >
              {isSaving
                ? 'Adding dependency…'
                : isDuplicateDependency()
                ? 'Already added'
                : selectedThread
                ? `Block issue #${targetIssues?.find((i) => i.id === targetIssueId)?.issue_number || '?'} with: ${selectedThread.title} #${sourceIssues?.find((i) => i.id === sourceIssueId)?.issue_number || '?'}`
                : 'Select a prerequisite'}
            </button>
         </div>

         <div className="space-y-2">
           <h3 className="text-sm font-black uppercase tracking-widest text-stone-300">This series is blocked by</h3>
           {isLoadingDeps ? (
             <p className="text-xs text-stone-500">Loading dependencies…</p>
           ) : dependencies.blocked_by.length === 0 ? (
             <p className="text-xs text-stone-500">No prerequisites yet.</p>
           ) : (
             Array.from(groupByThread(dependencies.blocked_by, 'source_label')).map(([threadName, deps]) => (
               <div key={threadName} className="space-y-1">
                 <p className="text-xs font-bold text-stone-400 break-words min-w-0">{threadName}</p>
               {deps.map((dep) => {
                 const title = dep.is_issue_level && dep.source_label && dep.target_label
                   ? `${dep.source_label} → ${dep.target_label}`
                   : dep.source_label ?? (dep.source_issue_id ? `Issue #${dep.source_issue_id}` : `Series #${dep.source_thread_id}`)
                 return (
                   <DependencyRow
                     key={dep.id}
                     dependency={dep}
                     title={title}
                     subtitle={dep.source_issue_id ? 'Issue-level block' : 'Series-level block'}
                     onDelete={handleDeleteDependency}
                     onEditNote={handleStartEditNote}
                     editingNoteId={editingNoteId}
                     noteText={noteText}
                     onNoteChange={setNoteText}
                     onSaveNote={handleSaveNote}
                     onCancelNote={handleCancelEditNote}
                     isSavingNote={isSavingNote}
                   />
                 )
               })}
               </div>
             ))
           )}
         </div>

         <div className="space-y-2">
           <h3 className="text-sm font-black uppercase tracking-widest text-stone-300">This series blocks</h3>
           {isLoadingDeps ? (
             <p className="text-xs text-stone-500">Loading dependencies…</p>
           ) : dependencies.blocking.length === 0 ? (
             <p className="text-xs text-stone-500">No dependent series yet.</p>
           ) : (
             Array.from(groupByThread(dependencies.blocking, 'target_label')).map(([threadName, deps]) => (
               <div key={threadName} className="space-y-1">
                 <p className="text-xs font-bold text-stone-400 break-words min-w-0">{threadName}</p>
               {deps.map((dep) => {
                 const title = dep.is_issue_level && dep.source_label && dep.target_label
                   ? `${dep.source_label} → ${dep.target_label}`
                   : dep.target_label ?? (dep.target_issue_id ? `Issue #${dep.target_issue_id}` : `Series #${dep.target_thread_id}`)
                 return (
                   <DependencyRow
                     key={dep.id}
                     dependency={dep}
                     title={title}
                     subtitle={dep.target_issue_id ? 'Issue-level block' : 'Series-level block'}
                     onDelete={handleDeleteDependency}
                     onEditNote={handleStartEditNote}
                     editingNoteId={editingNoteId}
                     noteText={noteText}
                     onNoteChange={setNoteText}
                     onSaveNote={handleSaveNote}
                     onCancelNote={handleCancelEditNote}
                     isSavingNote={isSavingNote}
                   />
                 )
               })}
               </div>
             ))
           )}
         </div>

         {error && (
           <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-3 py-2 rounded-xl text-xs">
             {error}
           </div>
         )}
       </div>
    </Modal>
  )
}

interface DependencyRowProps {
  dependency: Dependency
  title: string
  subtitle: string
  onDelete: (id: number) => void
  onEditNote: (dep: Dependency) => void
  editingNoteId: number | null
  noteText: string
  onNoteChange: (text: string) => void
  onSaveNote: (id: number) => void
  onCancelNote: () => void
  isSavingNote: boolean
}

function DependencyRow({
  dependency,
  title,
  subtitle,
  onDelete,
  onEditNote,
  editingNoteId,
  noteText,
  onNoteChange,
  onSaveNote,
  onCancelNote,
  isSavingNote,
}: DependencyRowProps) {
  const isEditing = editingNoteId === dependency.id

  return (
    <div className="flex flex-col gap-2 bg-white/5 border border-white/10 rounded-xl px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-stone-300 truncate">{title}</p>
          <p className="text-[10px] font-bold uppercase tracking-widest text-stone-500">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => onDelete(dependency.id)}
          className="text-red-300 hover:text-red-200 text-xs font-black uppercase tracking-widest"
        >
          Remove
        </button>
      </div>
      {isEditing ? (
        <div className="flex gap-2">
          <input
            type="text"
            value={noteText}
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="Add a note..."
            maxLength={255}
            className="flex-1 rounded-lg px-2 py-1 text-xs form-control"
          />
          <button
            type="button"
            onClick={() => onSaveNote(dependency.id)}
            disabled={isSavingNote || noteText.length > 255}
            className="min-h-[44px] px-3 bg-amber-600/20 border border-amber-500/40 text-amber-300 rounded-lg text-xs font-black uppercase tracking-widest disabled:opacity-50"
          >
            {isSavingNote ? 'Saving...' : 'Save'}
          </button>
          <button
            type="button"
            onClick={onCancelNote}
            className="min-h-[44px] px-3 text-stone-400 hover:text-stone-300 text-xs font-black uppercase tracking-widest"
          >
            Cancel
          </button>
        </div>
      ) : dependency.note ? (
        <div className="flex items-center gap-2">
          <p className="text-xs text-stone-400 italic flex-1">{dependency.note}</p>
          <button
            type="button"
            onClick={() => onEditNote(dependency)}
            className="text-stone-500 hover:text-stone-300 text-[10px] font-black uppercase tracking-widest"
          >
            Edit note
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => onEditNote(dependency)}
          className="text-stone-600 hover:text-stone-400 text-[10px] font-black uppercase tracking-widest text-left"
        >
          + Add note
        </button>
      )}
    </div>
  )
}
