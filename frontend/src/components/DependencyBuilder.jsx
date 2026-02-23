import { useCallback, useEffect, useMemo, useState } from 'react'
import Modal from './Modal'
import { dependenciesApi, threadsApi } from '../services/api'

export default function DependencyBuilder({ thread, isOpen, onClose, onChanged }) {
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [selectedThreadId, setSelectedThreadId] = useState(null)
  const [isSearching, setIsSearching] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [dependencies, setDependencies] = useState({ blocking: [], blocked_by: [] })
  const [isLoadingDeps, setIsLoadingDeps] = useState(false)

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
    } catch (loadError) {
      setError(loadError?.response?.data?.detail || 'Failed to load dependencies.')
    } finally {
      setIsLoadingDeps(false)
    }
  }, [thread?.id])

  useEffect(() => {
    if (!isOpen || !thread?.id) return
    setSearchQuery('')
    setSearchResults([])
    setSelectedThreadId(null)
    setError('')
    loadDependencies()
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
        const filtered = candidates.filter((candidate) => candidate.id !== thread.id)
        setSearchResults(filtered)
      } catch (searchError) {
        if (!isCurrent) return
        setError(searchError?.response?.data?.detail || 'Thread search failed.')
        setSearchResults([])
      } finally {
        if (!isCurrent) return
        setIsSearching(false)
      }
    }, 300)

    return () => {
      isCurrent = false
      clearTimeout(timeout)
    }
  }, [searchQuery, isOpen, thread?.id])

  async function handleCreateDependency() {
    if (!thread?.id || !selectedThreadId) return

    setIsSaving(true)
    setError('')
    try {
      await dependenciesApi.createDependency({ sourceId: selectedThreadId, targetId: thread.id })
      setSearchQuery('')
      setSearchResults([])
      setSelectedThreadId(null)
      await loadDependencies()
      onChanged?.()
    } catch (saveError) {
      setError(saveError?.response?.data?.detail || 'Failed to create dependency.')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDeleteDependency(dependencyId) {
    setError('')
    try {
      await dependenciesApi.deleteDependency(dependencyId)
      await loadDependencies()
      onChanged?.()
    } catch (deleteError) {
      setError(deleteError?.response?.data?.detail || 'Failed to remove dependency.')
    }
  }

  return (
    <Modal isOpen={isOpen} title={`Dependencies: ${thread?.title || ''}`} onClose={onClose}>
      <div className="space-y-4">
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
          <button
            type="button"
            onClick={handleCreateDependency}
            disabled={!selectedThread || isSaving}
            className="w-full py-2 glass-button text-xs font-black uppercase tracking-widest disabled:opacity-50"
          >
            {isSaving ? 'Adding dependency…' : selectedThread ? `Block with: ${selectedThread.title}` : 'Select a prerequisite'}
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
                title={`Thread #${dep.source_thread_id}`}
                subtitle={`Blocks this thread`}
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
                title={`Thread #${dep.target_thread_id}`}
                subtitle={`Depends on this thread`}
                onDelete={handleDeleteDependency}
              />
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

function DependencyRow({ dependencyId, title, subtitle, onDelete }) {
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
