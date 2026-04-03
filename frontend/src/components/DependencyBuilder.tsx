import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import Modal from './Modal'
import DependencyFlowchart from './DependencyFlowchart'
import ReadingOrderTimeline from './ReadingOrderTimeline'
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import type { Dependency, FlowchartDependency, FlowchartNode, Issue, Thread, ThreadDependenciesResponse } from '../types'
import { getApiErrorDetail } from '../utils/apiError'
import { useToast } from '../contexts/ToastContext'

function getDefaultDependencyMode(thread: Thread | null): 'thread' | 'issue' {
  return thread?.next_unread_issue_id ? 'issue' : 'thread'
}

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

export default function DependencyBuilder({ thread, isOpen, onClose, onChanged }: DependencyBuilderProps) {
  const [dependencyMode, setDependencyMode] = useState(getDefaultDependencyMode(thread))
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Thread[]>([])
  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [dependencies, setDependencies] = useState<ThreadDependenciesResponse>({ blocking: [], blocked_by: [] })
  const [isLoadingDeps, setIsLoadingDeps] = useState(false)
  const [showReadingOrder, setShowReadingOrder] = useState(false)
  const [readingView, setReadingView] = useState<'timeline' | 'graph'>('timeline')
  const [isGraphLoading, setIsGraphLoading] = useState(false)
  const [flowchartThreads, setFlowchartThreads] = useState<Thread[]>([])
  const [flowchartDependencies, setFlowchartDependencies] = useState<FlowchartDependency[]>([])
  const [flowchartIssueNodes, setFlowchartIssueNodes] = useState<FlowchartNode[]>([])
  const [blockedIds, setBlockedIds] = useState<Set<number>>(new Set())
  const [sourceIssueId, setSourceIssueId] = useState<number | null>(null)
  const [targetIssueId, setTargetIssueId] = useState<number | null>(null)
  const [sourceIssues, setSourceIssues] = useState<Issue[]>([])
  const [targetIssues, setTargetIssues] = useState<Issue[]>([])
  const [isLoadingSourceIssues, setIsLoadingSourceIssues] = useState(false)
  const [isLoadingTargetIssues, setIsLoadingTargetIssues] = useState(false)
  // Inline migration state (item 7)
  const [showInlineMigration, setShowInlineMigration] = useState(false)
  const [migrationLastRead, setMigrationLastRead] = useState('')
  const [migrationTotal, setMigrationTotal] = useState('')
  const [isMigrating, setIsMigrating] = useState(false)
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
const [isSavingNote, setIsSavingNote] = useState(false)

  const selectedThread = useMemo(
    () => searchResults.find((candidate) => candidate.id === selectedThreadId) || null,
    [searchResults, selectedThreadId]
  )

  const loadDependencies = useCallback(async () => {
    if (!thread?.id) return
    setIsLoadingDeps(true)
    setError('')
    try {
      const data = await dependenciesApi.listThreadDependencies(thread.id)
      setDependencies(data)
    } catch (loadError: unknown) {
      setError(getApiErrorDetail(loadError))
    } finally {
      setIsLoadingDeps(false)
    }
  }, [thread?.id])

  /**
   * Build the full graph of threads and dependencies for the flowchart.
   * Synthesizes virtual thread-level edges from issue-level deps so they
   * show as dashed connections in the flowchart.
   */
  const loadFlowchartData = useCallback(async () => {
    if (!thread?.id) return
    try {
      const [depsData, allBlockedIds] = await Promise.all([
        dependenciesApi.listThreadDependencies(thread.id),
        dependenciesApi.listBlockedThreadIds(),
      ])

      const relatedIds = new Set([thread.id])
      const allDeps = [...depsData.blocking, ...depsData.blocked_by]

      

      // Thread-level deps map directly to FlowchartDependency
      const threadDeps: FlowchartDependency[] = allDeps
        .filter((dep) => dep.source_thread_id != null && dep.target_thread_id != null)
        .map((dep) => ({
          id: String(dep.id),
          source_id: dep.source_thread_id as number,
          target_id: dep.target_thread_id as number,
          created_at: dep.created_at,
        }))

      // Collect related thread IDs from thread-level deps
      for (const dep of threadDeps) {
        relatedIds.add(dep.source_id)
        relatedIds.add(dep.target_id)
      }

      // Issue-level deps → issue nodes + direct edges between them
      const issueOnlyDeps = allDeps.filter(
        (dep) => dep.source_thread_id == null || dep.target_thread_id == null
      )
      const issueNodeMap = new Map<number, FlowchartNode>()
      const issueEdges: FlowchartDependency[] = []

      

      for (const d of issueOnlyDeps) {
        if (!d.source_issue_id || !d.target_issue_id) continue
        if (!d.source_issue_thread_id || !d.target_issue_thread_id) continue

        // Use negative issue ID to avoid thread ID collisions
        const srcNodeId = -d.source_issue_id
        if (!issueNodeMap.has(srcNodeId)) {
          issueNodeMap.set(srcNodeId, {
            id: srcNodeId,
            title: d.source_label ?? `Issue #${d.source_issue_id}`,
            x: 0, y: 0,
            isBlocked: false,
            isIssueNode: true,
            parentThreadId: d.source_issue_thread_id,
          })
        }

        const tgtNodeId = -d.target_issue_id
        if (!issueNodeMap.has(tgtNodeId)) {
          issueNodeMap.set(tgtNodeId, {
            id: tgtNodeId,
            title: d.target_label ?? `Issue #${d.target_issue_id}`,
            x: 0, y: 0,
            isBlocked: false,
            isIssueNode: true,
            parentThreadId: d.target_issue_thread_id,
          })
        }

 issueEdges.push({
 id: d.id,
 source_id: srcNodeId,
          target_id: tgtNodeId,
          is_issue_level: true,
          source_parent_thread_id: d.source_issue_thread_id,
          target_parent_thread_id: d.target_issue_thread_id,
          created_at: d.created_at,
        })

        // Ensure parent threads are loaded for context
        relatedIds.add(d.source_issue_thread_id)
        relatedIds.add(d.target_issue_thread_id)
      }

      

      const allEdges = [...threadDeps, ...issueEdges]

    const allThreads = await threadsApi.list()
    const relatedThreads = allThreads.threads.filter((t) => relatedIds.has(t.id))

      

      setFlowchartThreads(relatedThreads)
      setFlowchartDependencies(allEdges)
      setFlowchartIssueNodes(Array.from(issueNodeMap.values()))
      setBlockedIds(new Set(allBlockedIds))
    } catch (err) {
      console.error('[loadFlowchartData] Error:', err)
      setFlowchartThreads([])
      setFlowchartDependencies([])
      setFlowchartIssueNodes([])
    }
  }, [thread?.id])

  useEffect(() => {
    if (!isOpen || !thread?.id) return
    setSearchQuery('')
    setSearchResults([])
    setSelectedThreadId(null)
    setError('')
    setShowReadingOrder(false)
    setReadingView('timeline')
    setDependencyMode(getDefaultDependencyMode(thread))
    setSourceIssueId(null)
    setTargetIssueId(null)
    setSourceIssues([])
    setTargetIssues([])
    setShowInlineMigration(false)
    
    // Clean up any pending deletion when modal closes
    if (pendingDeletion) {
      clearTimeout(pendingDeletion.timeoutId)
      // Fire DELETE immediately (commit the deletion)
      dependenciesApi.deleteDependency(pendingDeletion.dependencyId)
        .then(() => {
          // Deletion succeeded, reload dependencies
          onChanged?.()
        })
        .catch((deleteError: unknown) => {
          // If deletion fails, restore the dependency
          setError(getApiErrorDetail(deleteError))
          // Restore the dependency
          setDependencies((prev) => ({
            blocking: [...prev.blocking, pendingDeletion.dependencyData],
            blocked_by: [...prev.blocked_by, pendingDeletion.dependencyData],
          }))
        })
        .finally(() => {
          toast.removeToast(pendingDeletion.toastId)
          setPendingDeletion(null)
        })
    }
    
    loadDependencies()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, thread?.id, loadDependencies])

  useEffect(() => {
    if (!isOpen) return
    const query = searchQuery.trim()
    if (query.length < 2) {
      setSearchResults([])
      return
    }

    let isCurrent = true
    const timeout = setTimeout(async () => {
      if (!isCurrent) return
      setIsSearching(true)
      setError('')
      try {
    const candidates = await threadsApi.list({ search: query })
    if (!isCurrent) return
    const currentThreadId = thread?.id
    const filtered =  currentThreadId == null
      ? candidates.threads
      : candidates.threads.filter((candidate) => candidate.id !== currentThreadId)
        setSearchResults(filtered)
      } catch (searchError: unknown) {
        if (!isCurrent) return
        setError(getApiErrorDetail(searchError))
        setSearchResults([])
      } finally {
        if (isCurrent) {
          setIsSearching(false)
        }
      }
    }, 300)

    return () => {
      isCurrent = false
      clearTimeout(timeout)
    }
  }, [searchQuery, isOpen, thread?.id])

  // Check if selected thread needs migration when in issue mode
  const selectedThreadNeedsMigration = useMemo(() => {
    if (dependencyMode !== 'issue' || !selectedThread) return false
    return selectedThread.total_issues === null || selectedThread.total_issues === undefined
  }, [dependencyMode, selectedThread])

  useEffect(() => {
    if (!isOpen || dependencyMode !== 'issue' || !selectedThreadId || !thread?.id) {
      setSourceIssues([])
      setTargetIssues([])
      setSourceIssueId(null)
      setTargetIssueId(null)
      return
    }

    // Don't fetch issues if the source thread needs migration
    if (selectedThreadNeedsMigration) {
      setSourceIssues([])
      setTargetIssues([])
      setSourceIssueId(null)
      setTargetIssueId(null)
      return
    }

    let isCurrent = true
    const fetchIssues = async () => {
      setIsLoadingSourceIssues(true)
      setIsLoadingTargetIssues(true)
      setError('')
      try {
        const [sourceData, targetData] = await Promise.all([
          issuesApi.list(selectedThreadId),
          issuesApi.list(thread.id),
        ])
        if (!isCurrent) return
        setSourceIssues(sourceData.issues || [])
        setTargetIssues(targetData.issues || [])
        setSourceIssueId(sourceData.issues?.find((i) => i.status === 'unread')?.id || null)
        setTargetIssueId(targetData.issues?.find((i) => i.status === 'unread')?.id || null)
      } catch (issuesError: unknown) {
        if (!isCurrent) return
        setError(getApiErrorDetail(issuesError))
        setSourceIssues([])
        setTargetIssues([])
        setSourceIssueId(null)
        setTargetIssueId(null)
      } finally {
        if (isCurrent) {
          setIsLoadingSourceIssues(false)
          setIsLoadingTargetIssues(false)
        }
      }
    }

    fetchIssues()

    return () => {
      isCurrent = false
    }
  }, [selectedThreadId, dependencyMode, isOpen, thread?.id, selectedThreadNeedsMigration])

   function isDuplicateDependency(): boolean {
     if (!thread?.id || !selectedThreadId) return false

     if (dependencyMode === 'thread') {
       // Check if thread-level dependency already exists
       return (
         dependencies.blocking.some(
           (dep) => dep.source_thread_id === selectedThreadId && dep.target_thread_id === thread.id
         ) ||
         dependencies.blocked_by.some(
           (dep) => dep.source_thread_id === selectedThreadId && dep.target_thread_id === thread.id
         )
       )
     } else {
       // Check if issue-level dependency already exists
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
   }

   async function handleInlineMigration(e: FormEvent) {
    e.preventDefault()
    if (!selectedThreadId) return
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

    setIsMigrating(true)
    setError('')
    try {
      const updatedThread = await issuesApi.migrateThread(selectedThreadId, lastRead, total)
      // Refresh search results with updated thread data
      setSearchResults((prev) =>
        prev.map((t) => (t.id === selectedThreadId ? updatedThread : t))
      )
      setShowInlineMigration(false)
      setMigrationLastRead('')
      setMigrationTotal('')
    } catch (migrationError: unknown) {
      setError(getApiErrorDetail(migrationError))
    } finally {
      setIsMigrating(false)
    }
  }

  async function handleCreateDependency() {
    if (!thread?.id || !selectedThreadId) return

    const targetHasIssueTracking = thread.total_issues !== null && thread.total_issues !== undefined
    if (dependencyMode === 'issue' && !targetHasIssueTracking) {
      setError('Target thread must be migrated to issue tracking before adding issue dependencies.')
      return
    }

    if (dependencyMode === 'issue' && (!sourceIssueId || !targetIssueId)) {
      setError('Both prerequisite issue and target issue must be selected.')
      return
    }

    setIsSaving(true)
    setError('')
    try {
      if (dependencyMode === 'issue') {
        await dependenciesApi.createDependency({
          sourceType: 'issue',
          sourceId: sourceIssueId!,
          targetType: 'issue',
          targetId: targetIssueId!,
        })
      } else {
        await dependenciesApi.createDependency({
          sourceType: 'thread',
          sourceId: selectedThreadId,
          targetType: 'thread',
          targetId: thread.id,
        })
      }
      setSearchQuery('')
      setSearchResults([])
      setSelectedThreadId(null)
      setSourceIssueId(null)
      setTargetIssueId(null)
      setSourceIssues([])
      setTargetIssues([])
      await loadDependencies()
      await refreshGraphIfVisible()
      onChanged?.()
    } catch (saveError: unknown) {
      setError(getApiErrorDetail(saveError))
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteDependency(dependencyId: number) {
    setError('')
    try {
      // Find the dependency to delete
      const dependencyToDelete = [...dependencies.blocking, ...dependencies.blocked_by].find(
        (dep) => dep.id === dependencyId
      )

      if (!dependencyToDelete) return

      // Optimistic UI: remove immediately
      setDependencies((prev) => ({
        blocking: prev.blocking.filter((dep) => dep.id !== dependencyId),
        blocked_by: prev.blocked_by.filter((dep) => dep.id !== dependencyId),
      }))

      // Show undo toast with action button
      const message = dependencyToDelete.source_label && dependencyToDelete.target_label
        ? `${dependencyToDelete.source_label} → ${dependencyToDelete.target_label}`
        : `Dependency #${dependencyId}`

      const timeoutId = setTimeout(async () => {
        try {
          await dependenciesApi.deleteDependency(dependencyId)
          setPendingDeletion(null)
          await loadDependencies()
          await refreshGraphIfVisible()
          onChanged?.()
        } catch (deleteError: unknown) {
          setError(getApiErrorDetail(deleteError))
          // Restore the dependency if deletion fails
          await loadDependencies()
        }
      }, 5000)

      // Show toast and capture its ID
      const toastId = toast.showToast(
        `${message} removed.`,
        'info',
        {
          label: 'Undo',
          onClick: () => {
            clearTimeout(timeoutId)
            setPendingDeletion(null)

            // Restore the dependency
            setDependencies((prev) => ({
              blocking: [...prev.blocking, dependencyToDelete],
              blocked_by: [...prev.blocked_by, dependencyToDelete],
            }))

            toast.removeToast(toastId)
          }
        }
      )

      // Store pending deletion for undo
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
    if (noteText.length > 255) {
      setError('Note must be 255 characters or less.')
      return
    }
    setIsSavingNote(true)
    setError('')
    try {
      const updated = await dependenciesApi.updateDependency(dependencyId, noteText.trim() || null)
      setDependencies((prev) => ({
        ...prev,
        blocking: prev.blocking.map((d) => (d.id === dependencyId ? updated : d)),
        blocked_by: prev.blocked_by.map((d) => (d.id === dependencyId ? updated : d)),
      }))
      setEditingNoteId(null)
      setNoteText('')
    } catch (saveError: unknown) {
      setError(getApiErrorDetail(saveError))
    } finally {
      setIsSavingNote(false)
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
    setIsGraphLoading(true)
    try {
      await loadFlowchartData()
    } finally {
      setIsGraphLoading(false)
    }
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

  async function refreshGraphIfVisible() {
    if (showReadingOrder && readingView === 'graph') {
      await refreshGraphData()
    }
  }

  return (
    <Modal isOpen={isOpen} title={`Dependencies: ${thread?.title || ''}`} onClose={onClose}>
      <div className="space-y-4">
      {/* Flowchart toggle */}
      {thread && (dependencies.blocking.length > 0 || dependencies.blocked_by.length > 0) && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleToggleReadingOrder}
            className="w-full py-3 glass-button text-xs font-black uppercase tracking-widest"
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
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setDependencyMode('issue')}
              className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                dependencyMode === 'issue'
                  ? 'bg-amber-600/20 border-amber-500/40 text-amber-300'
                  : 'bg-white/5 border-white/10 text-stone-400'
              }`}
            >
              Issue Level
            </button>
            <button
              type="button"
              onClick={() => setDependencyMode('thread')}
              className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                dependencyMode === 'thread'
                  ? 'bg-amber-600/20 border-amber-500/40 text-amber-300'
                  : 'bg-white/5 border-white/10 text-stone-400'
              }`}
            >
              Thread Level
            </button>
          </div>
          {dependencyMode === 'issue' && (
            <p className="text-xs text-stone-500">
              Uses each thread&apos;s next unread issue.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label htmlFor="search-prereq-thread" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
            Search prerequisite thread
          </label>
          <input
            id="search-prereq-thread"
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Type at least 2 characters"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
          />
          {isSearching && <p className="text-xs text-stone-500">Searching…</p>}
          {!isSearching && searchQuery.trim().length >= 2 && searchResults.length === 0 && (
            <p className="text-xs text-stone-500">No matching threads found.</p>
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

           {/* Inline migration prompt (item 7) */}
           {dependencyMode === 'issue' && selectedThread && selectedThreadNeedsMigration && (
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
                    <div className="flex gap-2">
                      <div className="flex-1">
                        <label htmlFor="migration-last-read" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">Last issue read</label>
                        <input
                          id="migration-last-read"
                          type="number"
                          min="0"
                          value={migrationLastRead}
                          onChange={(e) => setMigrationLastRead(e.target.value)}
                          className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-sm text-stone-300"
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
                          className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-sm text-stone-300"
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

           {dependencyMode === 'issue' && selectedThread && !selectedThreadNeedsMigration && (
             <div className="space-y-2">
               {isLoadingSourceIssues || isLoadingTargetIssues ? (
                 <p className="text-xs text-stone-500">Loading issues…</p>
               ) : (
                 <>
                   <div>
                     <label htmlFor="source-issue" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                       Prerequisite issue
                     </label>
                     <select
                       id="source-issue"
                       value={sourceIssueId || ''}
                       onChange={(event) => setSourceIssueId(event.target.value ? Number(event.target.value) : null)}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                     >
                       <option value="">Select an issue</option>
                        {sourceIssues.map((issue) => (
                          <option key={issue.id} value={issue.id}>
                            #{issue.issue_number} {issue.status === 'read' ? '✅' : '🟢'}
                          </option>
                        ))}
                     </select>
                   </div>
                   <div>
                     <label htmlFor="target-issue" className="text-[10px] font-bold uppercase tracking-widest text-stone-500">
                       Target issue
                     </label>
                     <select
                       id="target-issue"
                       value={targetIssueId || ''}
                       onChange={(event) => setTargetIssueId(event.target.value ? Number(event.target.value) : null)}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-stone-300"
                     >
                       <option value="">Select an issue</option>
                        {targetIssues.map((issue) => (
                          <option key={issue.id} value={issue.id}>
                            #{issue.issue_number} {issue.status === 'read' ? '✅' : '🟢'}
                          </option>
                        ))}
                     </select>
                   </div>
                 </>
               )}
             </div>
           )}
            <button
              type="button"
              onClick={handleCreateDependency}
              disabled={
                dependencyMode === 'issue'
                  ? !selectedThread || selectedThreadNeedsMigration || !sourceIssueId || !targetIssueId || isSaving || isDuplicateDependency()
                  : !selectedThread || isSaving || isDuplicateDependency()
              }
              className="w-full py-2 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-50"
            >
               {isSaving
                 ? 'Adding dependency…'
                 : isDuplicateDependency()
                 ? 'Already added'
                 : selectedThread
                 ? dependencyMode === 'issue'
                     ? `Block issue #${targetIssues.find((i) => i.id === targetIssueId)?.issue_number || '?'} with: ${selectedThread.title} #${sourceIssues.find((i) => i.id === sourceIssueId)?.issue_number || '?'}`
                     : `Block with thread: ${selectedThread.title}`
                 : 'Select a prerequisite'}
            </button>
         </div>

        <div className="space-y-2">
          <h3 className="text-sm font-black uppercase tracking-widest text-stone-300">This thread is blocked by</h3>
          {isLoadingDeps ? (
            <p className="text-xs text-stone-500">Loading dependencies…</p>
          ) : dependencies.blocked_by.length === 0 ? (
            <p className="text-xs text-stone-500">No prerequisites yet.</p>
          ) : (
            Array.from(groupByThread(dependencies.blocked_by, 'source_label')).map(([threadName, deps]) => (
              <div key={threadName} className="space-y-1">
                <p className="text-xs font-bold text-stone-400 truncate">{threadName}</p>
              {deps.map((dep) => {
                const title = dep.is_issue_level && dep.source_label && dep.target_label
                  ? `${dep.source_label} → ${dep.target_label}`
                  : dep.source_label ?? (dep.source_issue_id ? `Issue #${dep.source_issue_id}` : `Thread #${dep.source_thread_id}`)
                return (
                  <DependencyRow
                    key={dep.id}
                    dependency={dep}
                    title={title}
                    subtitle={dep.source_issue_id ? 'Issue-level block' : 'Thread-level block'}
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
          <h3 className="text-sm font-black uppercase tracking-widest text-stone-300">This thread blocks</h3>
          {isLoadingDeps ? (
            <p className="text-xs text-stone-500">Loading dependencies…</p>
          ) : dependencies.blocking.length === 0 ? (
            <p className="text-xs text-stone-500">No dependent threads yet.</p>
          ) : (
            Array.from(groupByThread(dependencies.blocking, 'target_label')).map(([threadName, deps]) => (
              <div key={threadName} className="space-y-1">
                <p className="text-xs font-bold text-stone-400 truncate">{threadName}</p>
              {deps.map((dep) => {
                const title = dep.is_issue_level && dep.source_label && dep.target_label
                  ? `${dep.source_label} → ${dep.target_label}`
                  : dep.target_label ?? (dep.target_issue_id ? `Issue #${dep.target_issue_id}` : `Thread #${dep.target_thread_id}`)
                return (
                  <DependencyRow
                    key={dep.id}
                    dependency={dep}
                    title={title}
                    subtitle={dep.target_issue_id ? 'Issue-level block' : 'Thread-level block'}
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
            className="flex-1 bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-xs text-stone-300"
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
