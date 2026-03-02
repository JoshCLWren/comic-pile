import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import Modal from './Modal'
import DependencyFlowchart from './DependencyFlowchart'
import { dependenciesApi, threadsApi } from '../services/api'
import { issuesApi } from '../services/api-issues'
import type { Dependency, FlowchartDependency, Issue, Thread, ThreadDependenciesResponse } from '../types'
import { getApiErrorDetail } from '../utils/apiError'

function getDefaultDependencyMode(thread: Thread | null): 'thread' | 'issue' {
  return thread?.next_unread_issue_id ? 'issue' : 'thread'
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
  const [showFlowchart, setShowFlowchart] = useState(false)
  const [flowchartThreads, setFlowchartThreads] = useState<Thread[]>([])
  const [flowchartDependencies, setFlowchartDependencies] = useState<FlowchartDependency[]>([])
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
          id: dep.id,
          source_thread_id: dep.source_thread_id as number,
          target_thread_id: dep.target_thread_id as number,
          created_at: dep.created_at,
        }))

      // Issue-level deps → virtual thread edges (dashed), deduplicated by thread pair
      const issueOnlyDeps = allDeps.filter(
        (dep) => dep.source_thread_id == null || dep.target_thread_id == null
      )
      const seenPairs = new Set<string>()
      const virtualEdges: FlowchartDependency[] = []
      for (const d of issueOnlyDeps) {
        if (!d.source_issue_thread_id || !d.target_issue_thread_id) continue
        const pairKey = `${d.source_issue_thread_id}->${d.target_issue_thread_id}`
        if (seenPairs.has(pairKey)) continue
        seenPairs.add(pairKey)
        virtualEdges.push({
          id: -(d.source_issue_thread_id * 100000 + d.target_issue_thread_id),
          source_thread_id: d.source_issue_thread_id,
          target_thread_id: d.target_issue_thread_id,
          is_issue_level: true,
          created_at: d.created_at,
        })
      }

      // Collect related thread IDs from BOTH real and virtual edges
      for (const dep of threadDeps) {
        relatedIds.add(dep.source_thread_id)
        relatedIds.add(dep.target_thread_id)
      }
      for (const edge of virtualEdges) {
        relatedIds.add(edge.source_thread_id)
        relatedIds.add(edge.target_thread_id)
      }

      const allEdges = [...threadDeps, ...virtualEdges]

      const allThreads = await threadsApi.list()
      const relatedThreads = allThreads.filter((t) => relatedIds.has(t.id))

      setFlowchartThreads(relatedThreads)
      setFlowchartDependencies(allEdges)
      setBlockedIds(new Set(allBlockedIds))
    } catch {
      setFlowchartThreads([])
      setFlowchartDependencies([])
    }
  }, [thread?.id])

  useEffect(() => {
    if (!isOpen || !thread?.id) return
    setSearchQuery('')
    setSearchResults([])
    setSelectedThreadId(null)
    setError('')
    setShowFlowchart(false)
    setDependencyMode(getDefaultDependencyMode(thread))
    setSourceIssueId(null)
    setTargetIssueId(null)
    setSourceIssues([])
    setTargetIssues([])
    setShowInlineMigration(false)
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
        const filtered =
          currentThreadId == null
            ? candidates
            : candidates.filter((candidate) => candidate.id !== currentThreadId)
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

  async function handleInlineMigration(e: FormEvent) {
    e.preventDefault()
    if (!selectedThreadId) return
    if (!migrationLastRead.trim() || !migrationTotal.trim()) {
      setError('Both fields are required for migration.')
      return
    }
    const lastRead = Number(migrationLastRead)
    const total = Number(migrationTotal)
    if (Number.isNaN(lastRead) || Number.isNaN(total) || total < 1 || lastRead < 0 || lastRead > total) {
      setError('Invalid migration values. Last read must be 0-total.')
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
      if (showFlowchart) await loadFlowchartData()
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
      await dependenciesApi.deleteDependency(dependencyId)
      await loadDependencies()
      if (showFlowchart) await loadFlowchartData()
      onChanged?.()
    } catch (deleteError: unknown) {
      setError(getApiErrorDetail(deleteError))
    }
  }

  async function handleToggleFlowchart() {
    if (!showFlowchart) {
      await loadFlowchartData()
    }
    setShowFlowchart((prev) => !prev)
  }

  const hasDependencies = dependencies.blocking.length > 0 || dependencies.blocked_by.length > 0

  return (
    <Modal isOpen={isOpen} title={`Dependencies: ${thread?.title || ''}`} onClose={onClose}>
      <div className="space-y-4">
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Dependency type
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setDependencyMode('issue')}
              className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                dependencyMode === 'issue'
                  ? 'bg-teal-500/20 border-teal-400/40 text-teal-200'
                  : 'bg-white/5 border-white/10 text-slate-400'
              }`}
            >
              Issue Level
            </button>
            <button
              type="button"
              onClick={() => setDependencyMode('thread')}
              className={`py-2 rounded-xl border text-xs font-black uppercase tracking-widest ${
                dependencyMode === 'thread'
                  ? 'bg-teal-500/20 border-teal-400/40 text-teal-200'
                  : 'bg-white/5 border-white/10 text-slate-400'
              }`}
            >
              Thread Level
            </button>
          </div>
          {dependencyMode === 'issue' && (
            <p className="text-xs text-slate-500">
              Uses each thread&apos;s next unread issue.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label htmlFor="search-prereq-thread" className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
            Search prerequisite thread
          </label>
          <input
            id="search-prereq-thread"
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Type at least 2 characters"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
          />
          {isSearching && <p className="text-xs text-slate-500">Searching…</p>}
          {!isSearching && searchQuery.trim().length >= 2 && searchResults.length === 0 && (
            <p className="text-xs text-slate-500">No matching threads found.</p>
          )}
          {searchResults.length > 0 && (
            <div className="max-h-40 overflow-auto border border-white/10 rounded-xl bg-white/5">
              {searchResults.map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  onClick={() => setSelectedThreadId(candidate.id)}
                  className={`w-full text-left px-3 py-2 text-sm border-b last:border-b-0 border-white/5 hover:bg-white/10 ${
                    selectedThreadId === candidate.id ? 'bg-white/10 text-white' : 'text-slate-300'
                  }`}
                >
                  {candidate.title} <span className="text-xs text-slate-500">({candidate.format})</span>
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
                       <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Last issue read</label>
                       <input
                         type="number"
                         min="0"
                         value={migrationLastRead}
                         onChange={(e) => setMigrationLastRead(e.target.value)}
                         className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-sm text-slate-200"
                         required
                       />
                     </div>
                     <div className="flex-1">
                       <label className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Total issues</label>
                       <input
                         type="number"
                         min="1"
                         value={migrationTotal}
                         onChange={(e) => setMigrationTotal(e.target.value)}
                         className="w-full bg-white/5 border border-white/10 rounded-lg px-2 py-1 text-sm text-slate-200"
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
                 <p className="text-xs text-slate-500">Loading issues…</p>
               ) : (
                 <>
                   <div>
                     <label htmlFor="source-issue" className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                       Prerequisite issue
                     </label>
                     <select
                       id="source-issue"
                       value={sourceIssueId || ''}
                       onChange={(event) => setSourceIssueId(event.target.value ? Number(event.target.value) : null)}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
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
                     <label htmlFor="target-issue" className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
                       Target issue
                     </label>
                     <select
                       id="target-issue"
                       value={targetIssueId || ''}
                       onChange={(event) => setTargetIssueId(event.target.value ? Number(event.target.value) : null)}
                       className="w-full bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-sm text-slate-200"
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
                 ? !selectedThread || selectedThreadNeedsMigration || !sourceIssueId || !targetIssueId || isSaving
                 : !selectedThread || isSaving
             }
             className="w-full py-2 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-50"
           >
              {isSaving
                ? 'Adding dependency…'
                : selectedThread
                  ? dependencyMode === 'issue'
                    ? `Block issue #${targetIssues.find((i) => i.id === targetIssueId)?.issue_number || '?'} with: ${selectedThread.title} #${sourceIssues.find((i) => i.id === sourceIssueId)?.issue_number || '?'}`
                    : `Block with thread: ${selectedThread.title}`
                  : 'Select a prerequisite'}
           </button>
         </div>

        <div className="space-y-2">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300">This thread is blocked by</h3>
          {isLoadingDeps ? (
            <p className="text-xs text-slate-500">Loading dependencies…</p>
          ) : dependencies.blocked_by.length === 0 ? (
            <p className="text-xs text-slate-500">No prerequisites yet.</p>
          ) : (
            dependencies.blocked_by.map((dep) => (
              <DependencyRow
                key={dep.id}
                dependencyId={dep.id}
                title={dep.source_label ?? (dep.source_issue_id ? `Issue #${dep.source_issue_id}` : `Thread #${dep.source_thread_id}`)}
                subtitle={dep.source_issue_id ? 'Issue-level block' : 'Thread-level block'}
                onDelete={handleDeleteDependency}
              />
            ))
          )}
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-black uppercase tracking-widest text-slate-300">This thread blocks</h3>
          {isLoadingDeps ? (
            <p className="text-xs text-slate-500">Loading dependencies…</p>
          ) : dependencies.blocking.length === 0 ? (
            <p className="text-xs text-slate-500">No dependent threads yet.</p>
          ) : (
            dependencies.blocking.map((dep) => (
              <DependencyRow
                key={dep.id}
                dependencyId={dep.id}
                title={dep.target_label ?? (dep.target_issue_id ? `Issue #${dep.target_issue_id}` : `Thread #${dep.target_thread_id}`)}
                subtitle={dep.target_issue_id ? 'Issue-level block' : 'Thread-level block'}
                onDelete={handleDeleteDependency}
              />
            ))
          )}
        </div>

        {/* Flowchart toggle */}
        {hasDependencies && (
          <div className="space-y-2">
            <button
              type="button"
              onClick={handleToggleFlowchart}
              className="w-full py-2 glass-button text-xs font-black uppercase tracking-widest"
              data-testid="toggle-flowchart"
            >
              {showFlowchart ? '▲ Hide Flowchart' : '▼ View Flowchart'}
            </button>

            {showFlowchart && (
              <DependencyFlowchart
                threads={flowchartThreads}
                dependencies={flowchartDependencies}
                blockedIds={blockedIds}
              />
            )}
          </div>
        )}

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
  dependencyId: number
  title: string
  subtitle: string
  onDelete: (id: number) => void
}

function DependencyRow({ dependencyId, title, subtitle, onDelete }: DependencyRowProps) {
  return (
    <div className="flex items-center justify-between gap-3 bg-white/5 border border-white/10 rounded-xl px-3 py-2">
      <div className="min-w-0">
        <p className="text-sm text-slate-200 truncate">{title}</p>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">{subtitle}</p>
      </div>
      <button
        type="button"
        onClick={() => onDelete(dependencyId)}
        className="text-red-300 hover:text-red-200 text-xs font-black uppercase tracking-widest"
      >
        Remove
      </button>
    </div>
  )
}
