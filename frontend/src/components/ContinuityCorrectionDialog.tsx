import { useEffect, useState } from 'react'
import Modal from './Modal'
import {
  dependencyGroupsApi,
  type DependencyGroup,
} from '../services/api-dependency-groups'
import { threadsApi } from '../services/api'
import { getApiErrorDetail } from '../utils/apiError'
import type { ConnectedThreadInfo, Thread } from '../types'

interface ContinuityCorrectionDialogProps {
  isOpen: boolean
  threadId: number
  issueId: number | null | undefined
  issueNumber: string | null | undefined
  threadTitle: string
  connectedThreads: ConnectedThreadInfo[]
  onClose: () => void
  onSuccess: () => void
}

type CrossoverMode = 'none' | 'existing' | 'new'

interface ResolvedThread {
  id: number
  title: string
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
  const [mode, setMode] = useState<CrossoverMode>('none')
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [isLoadingGroups, setIsLoadingGroups] = useState(false)
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [resolvedConnected, setResolvedConnected] = useState<ResolvedThread[]>([])
  const [connectedThreadsError, setConnectedThreadsError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen) return
    setMode('none')
    setSelectedGroupId(null)
    setNewName('')
    setError(null)
    setResult(null)
    setResolvedConnected([])
    setConnectedThreadsError(null)

    let isCurrent = true

    async function loadGroups() {
      setIsLoadingGroups(true)
      try {
        const loadedGroups = await dependencyGroupsApi.list()
        if (!isCurrent) return
        setGroups(loadedGroups)
      } catch (loadError: unknown) {
        if (!isCurrent) return
        setGroups([])
        setError(getApiErrorDetail(loadError))
      } finally {
        if (isCurrent) setIsLoadingGroups(false)
      }
    }

    async function resolveConnectedThreads() {
      if (connectedThreads.length === 0) return

      try {
        const resolved = await Promise.all(
          connectedThreads.map(async (connected): Promise<ResolvedThread | null> => {
            try {
              const thread: Thread = await threadsApi.get(connected.thread_id)
              return { id: thread.id, title: thread.title }
            } catch {
              return { id: connected.thread_id, title: connected.title }
            }
          }),
        )
        if (!isCurrent) return
        const filtered = resolved.filter((entry): entry is ResolvedThread => entry !== null)
        setResolvedConnected(filtered)
      } catch (err: unknown) {
        if (!isCurrent) return
        setConnectedThreadsError(getApiErrorDetail(err))
      }
    }

    void loadGroups()
    void resolveConnectedThreads()

    return () => {
      isCurrent = false
    }
  }, [isOpen, connectedThreads, threadId])

  const canSaveCurrentIssue = issueId != null
  const canSaveConnected = resolvedConnected.length > 0
  const hasSomethingToAdd =
    mode !== 'none' && (canSaveCurrentIssue || canSaveConnected)

  async function handleSaveMemberships() {
    setError(null)
    setResult(null)

    if (mode === 'existing' && selectedGroupId == null) {
      setError('Select an existing crossover.')
      return
    }
    const normalizedName = newName.trim()
    if (mode === 'new' && !normalizedName) {
      setError('Enter a crossover name.')
      return
    }

    setIsSaving(true)

    const addedLabels: string[] = []
    let createdGroup: DependencyGroup | null = null

    try {
      let targetGroup: DependencyGroup
      if (mode === 'new') {
        targetGroup = await dependencyGroupsApi.create(normalizedName)
        createdGroup = targetGroup
      } else {
        const existing = groups.find((candidate) => candidate.id === selectedGroupId)
        if (!existing) {
          throw new Error(`Crossover group ${selectedGroupId} not found.`)
        }
        targetGroup = existing
      }


      if (canSaveCurrentIssue) {
        await dependencyGroupsApi.addMember(targetGroup.id, { issue_id: issueId as number })
        addedLabels.push(`issue ${issueNumber ?? '?'}`)
      }
      for (const connected of resolvedConnected) {
        await dependencyGroupsApi.addMember(targetGroup.id, { thread_id: connected.id })
        addedLabels.push(connected.title)
      }

      setResult(`${addedLabels.join(', ')} added to ${targetGroup.name}.`)
      onSuccess()
    } catch (saveError: unknown) {
      const detail = getApiErrorDetail(saveError)
      if (createdGroup) {
        setError(`Created ${createdGroup.name}, but membership failed: ${detail}`)
      } else {
        setError(detail)
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      title="Correct Continuity"
      onClose={onClose}
      data-testid="continuity-correction-dialog"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      <section aria-labelledby="continuity-current-heading" className="rounded-2xl border border-white/10 bg-white/[0.04] p-3">
        <h3 id="continuity-current-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">
          Current Comic
        </h3>
        <p className="mt-1 text-sm text-stone-200">
          {threadTitle}
          {issueNumber != null ? <span className="text-amber-400"> #{issueNumber}</span> : null}
        </p>
      </section>

      {connectedThreads.length > 0 ? (
        <section aria-labelledby="continuity-connections-heading" className="rounded-2xl border border-blue-800/30 bg-blue-950/15 p-3">
          <h3 id="continuity-connections-heading" className="text-[10px] font-black uppercase tracking-[0.18em] text-blue-400">
            Verified connections
          </h3>
          {connectedThreadsError ? (
            <p className="mt-2 text-[11px] text-rose-300" role="alert">
              Could not load connection details: {connectedThreadsError}
            </p>
          ) : resolvedConnected.length === 0 ? (
            <p className="mt-2 text-[11px] text-stone-400" role="status">
              Resolving connected series…
            </p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Connected threads">
              {resolvedConnected.map((connected) => (
                <li
                  key={connected.id}
                  className="rounded-full border border-blue-800/40 bg-blue-900/20 px-2.5 py-1 text-[10px] font-bold text-blue-200"
                >
                  {connected.title}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[10px] font-bold text-stone-500">
            These will be added to the chosen crossover without re-searching.
          </p>
        </section>
      ) : null}

      <fieldset className="space-y-3" disabled={isSaving}>
        <legend className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Crossover membership</legend>
        <div className="flex gap-2">
          {(['none', 'existing', 'new'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setMode(option)}
              className={`flex-1 rounded-lg border py-2 text-[10px] font-black uppercase tracking-wider transition-colors ${
                mode === option
                  ? 'border-amber-600 bg-amber-600/20 text-amber-200'
                  : 'border-white/10 bg-white/5 text-stone-400'
              }`}
              aria-pressed={mode === option}
            >
              {option === 'none' ? 'Skip' : option === 'existing' ? 'Existing' : 'Create New'}
            </button>
          ))}
        </div>

        {mode === 'existing' ? (
          <label className="block">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Existing crossover</span>
            <select
              value={selectedGroupId ?? ''}
              onChange={(event) => setSelectedGroupId(event.target.value ? Number(event.target.value) : null)}
              className="mt-1 w-full rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:opacity-50"
              disabled={isLoadingGroups || isSaving}
            >
              <option value="">{isLoadingGroups ? 'Loading crossovers…' : 'Select a crossover'}</option>
              {groups.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {mode === 'new' ? (
          <label className="block">
            <span className="text-[10px] font-black uppercase tracking-[0.18em] text-stone-500">Crossover name</span>
            <input
              type="text"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              maxLength={200}
              placeholder="e.g. Ultimate Universe"
              className="mt-1 w-full rounded-xl border border-white/20 bg-white/5 px-3 py-2 text-sm text-stone-300 focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-500/30 disabled:opacity-50"
              disabled={isSaving}
            />
          </label>
        ) : null}

        <p className="text-[11px] font-bold text-stone-500">
          {canSaveCurrentIssue
            ? `Adds issue ${issueNumber ?? '?'} to the chosen crossover.`
            : 'No specific issue is available to add.'}
          {canSaveConnected ? ' Connected series will also be added.' : null}
        </p>
      </fieldset>

      {error ? (
        <p className="text-[11px] text-rose-300" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <p className="text-[11px] text-emerald-300" role="status">
          {result}
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onClose}
          className="flex-1 rounded-xl border border-white/10 bg-white/5 py-3 text-xs font-black uppercase tracking-wider text-stone-300 transition hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-amber-500"
          disabled={isSaving}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSaveMemberships}
          className="flex-1 rounded-xl border border-amber-600/50 bg-amber-600/20 py-3 text-xs font-black uppercase tracking-wider text-amber-200 transition hover:bg-amber-600/30 focus:outline-none focus:ring-2 focus:ring-amber-500 disabled:opacity-50"
          disabled={isSaving || !hasSomethingToAdd}
        >
          {isSaving ? 'Saving…' : 'Save Changes'}
        </button>
      </div>
    </Modal>
  )
}

export type { ContinuityCorrectionDialogProps }
