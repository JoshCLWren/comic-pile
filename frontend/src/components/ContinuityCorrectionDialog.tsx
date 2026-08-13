import { useState, useEffect, useCallback } from 'react'
import { dependencyGroupsApi, type DependencyGroup } from '../services/api-dependency-groups'
import { getApiErrorDetail } from '../utils/apiError'
import {
  ContinuityThreadSelector,
  ContinuityIssueSelector,
  type SelectedComic,
} from './continuity/ComicSelectors'

interface ContinuityCorrectionDialogProps {
  isOpen: boolean
  threadId: number
  issueId: number | null | undefined
  issueNumber: string | null | undefined
  threadTitle: string
  connectedThreads: any[]
  onClose: () => void
  onSuccess: () => void
}

export default function ContinuityCorrectionDialog({
  isOpen,
  threadId,
  issueId,
  issueNumber,
  threadTitle,
  connectedThreads,
  onClose,
  onSuccess,
}: ContinuityCorrectionDialogProps) {
  const [isLoadingThreads, setIsLoadingThreads] = useState(false)
  const [threads, setThreads] = useState<any[]>([])
  const [selectedThread, setSelectedThread] = useState<any>(null)
  const [selectedIssue, setSelectedIssue] = useState<any>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [mode, setMode] = useState<'none' | 'existing' | 'new'>('none')
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')

  useEffect(() => {
    if (isOpen) {
      fetchThreads()
    }
  }, [isOpen])

  async function fetchThreads() {
    setIsLoadingThreads(true)
    try {
      // Assuming there's a threadsApi.list() or similar. 
      // I need to check where threads are listed.
      // For now, I'll use a placeholder or check for existing API.
    } catch (err) {
      setError('Failed to load threads')
    } finally {
      setIsLoadingThreads(false)
    }
  }

  async function handleSaveCrossover() {
    setIsSaving(true)
    setError(null)
    setResult(null)
    try {
      let group: DependencyGroup | null = null
      if (mode === 'new') {
        if (!newName.trim()) throw new Error('Enter a crossover name')
        group = await dependencyGroupsApi.create(newName.trim())
      } else if (mode === 'existing') {
        if (!selectedGroupId) throw new Error('Select an existing crossover')
        group = await dependencyGroupsApi.get(selectedGroupId)
      } else {
        throw new Error('Select a crossover mode')
      }

      if (issueId) {
        await dependencyGroupsApi.addMember(group!.id, { issue_id: issueId })
      }
      
      setResult(`Added to ${group?.name}`)
      onSuccess()
    } catch (err) {
      setError(getApiErrorDetail(err))
    } finally {
      setIsSaving(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4 bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="relative w-full max-w-lg glass-card p-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4 pb-4">
          <h2 className="text-xl font-black tracking-tight text-stone-200 uppercase">Correct Continuity</h2>
          <button onClick={onClose} className="text-stone-500 hover:text-stone-300 text-2xl">&times;</button>
        </div>
        
        <div className="space-y-6">
          <div className="p-4 rounded-xl border border-white/10 bg-white/5">
            <p className="text-xs font-bold text-stone-500 uppercase mb-2">Current Comic</p>
            <p className="text-sm text-stone-200">{threadTitle} #{issueNumber}</p>
          </div>

          <div className="space-y-4">
            <p className="text-xs font-bold text-stone-500 uppercase">Crossover Membership</p>
            <div className="flex gap-2">
              {(['none', 'existing', 'new'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMode(m)}
                  className={`flex-1 py-2 text-xs font-bold uppercase rounded-lg border transition-colors ${
                    mode === m ? 'bg-amber-600/20 border-amber-600 text-amber-200' : 'bg-white/5 border-white/10 text-stone-400'
                  }`}
                >
                  {m === 'none' ? 'None' : m === 'existing' ? 'Existing' : 'Create New'}
                </button>
              ))}
            </div>

            {mode === 'existing' && (
              <select 
                value={selectedGroupId ?? ''} 
                onChange={(e) => setSelectedGroupId(Number(e.target.value) || null)}
                className="w-full rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300"
              >
                <option value="">Select crossover...</option>
                {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            )}

            {mode === 'new' && (
              <input 
                value={newName} 
                onChange={(e) => setNewName(e.target.value)} 
                placeholder="Crossover name..."
                className="w-full rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300"
              />
            )}
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}
          {result && <p className="text-xs text-green-400">{result}</p>}

          <div className="flex gap-3">
            <button onClick={onClose} className="flex-1 py-3 bg-white/5 border border-white/10 rounded-xl text-sm font-black uppercase text-stone-300">Cancel</button>
            <button 
              onClick={handleSaveCrossover} 
              disabled={isSaving}
              className="flex-1 py-3 bg-amber-600/20 border border-amber-600/50 rounded-xl text-sm font-black uppercase text-amber-200 disabled:opacity-50"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
