import { FormEvent, useCallback, useEffect, useState } from 'react'
import axios from 'axios'
import {
  dependencyGroupsApi,
  type DependencyGroup,
} from '../services/api-dependency-groups'

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return error instanceof Error && error.message ? error.message : fallback
}

export default function CrossoversPage() {
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [createError, setCreateError] = useState<string | null>(null)
  const [isCreating, setIsCreating] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')
  const [mutationError, setMutationError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const loadGroups = useCallback(async () => {
    setIsLoading(true)
    setLoadError(null)
    try {
      setGroups(await dependencyGroupsApi.list())
    } catch (error) {
      setLoadError(errorMessage(error, 'Unable to load crossovers.'))
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadGroups()
  }, [loadGroups])

  const createGroup = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName) {
      setCreateError('Enter a crossover name.')
      return
    }

    setCreateError(null)
    setIsCreating(true)
    try {
      const created = await dependencyGroupsApi.create(trimmedName)
      setGroups((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)))
      setName('')
    } catch (error) {
      setCreateError(errorMessage(error, 'Unable to create crossover.'))
    } finally {
      setIsCreating(false)
    }
  }

  const beginRename = (group: DependencyGroup) => {
    setMutationError(null)
    setEditingId(group.id)
    setEditingName(group.name)
  }

  const saveRename = async (groupId: number) => {
    const trimmedName = editingName.trim()
    if (!trimmedName) {
      setMutationError('Enter a crossover name.')
      return
    }

    setMutationError(null)
    setBusyId(groupId)
    try {
      const renamed = await dependencyGroupsApi.rename(groupId, trimmedName)
      setGroups((current) =>
        current
          .map((group) => (group.id === groupId ? renamed : group))
          .sort((a, b) => a.name.localeCompare(b.name)),
      )
      setEditingId(null)
      setEditingName('')
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to rename crossover.'))
    } finally {
      setBusyId(null)
    }
  }

  const deleteGroup = async (group: DependencyGroup) => {
    if (!window.confirm(`Delete “${group.name}”? Its comic memberships will be removed.`)) return

    setMutationError(null)
    setBusyId(group.id)
    try {
      await dependencyGroupsApi.delete(group.id)
      setGroups((current) => current.filter((item) => item.id !== group.id))
      if (expandedId === group.id) setExpandedId(null)
      if (editingId === group.id) setEditingId(null)
    } catch (error) {
      setMutationError(errorMessage(error, 'Unable to delete crossover.'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="space-y-6" aria-labelledby="crossovers-heading">
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.25em] text-amber-500">Continuity</p>
        <h1 id="crossovers-heading" className="mt-1 text-3xl font-black text-stone-100">Crossovers</h1>
        <p className="mt-2 max-w-2xl text-sm text-stone-400">
          Name connected comics so their continuity is easy to recognize across ComicPile. Membership does not create a reading block by itself.
        </p>
      </header>

      <form onSubmit={createGroup} className="rounded-2xl border border-stone-700 bg-stone-900/70 p-4" aria-label="Create crossover">
        <label htmlFor="crossover-name" className="block text-sm font-bold text-stone-200">New crossover</label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            id="crossover-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={200}
            className="min-w-0 flex-1 rounded-xl border border-stone-600 bg-stone-950 px-3 py-2.5 text-stone-100 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-500/30"
            placeholder="Age of Apocalypse"
            disabled={isCreating}
          />
          <button type="submit" disabled={isCreating} className="rounded-xl bg-amber-500 px-4 py-2.5 font-bold text-stone-950 disabled:cursor-not-allowed disabled:opacity-50">
            {isCreating ? 'Creating…' : 'Create crossover'}
          </button>
        </div>
        {createError && <p role="alert" className="mt-2 text-sm text-red-400">{createError}</p>}
      </form>

      {mutationError && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/40 p-3 text-sm text-red-300">{mutationError}</p>}

      {isLoading ? (
        <p role="status" className="rounded-2xl border border-stone-800 p-6 text-center text-stone-400">Loading crossovers…</p>
      ) : loadError ? (
        <div role="alert" className="rounded-2xl border border-red-800 bg-red-950/40 p-4 text-red-300">
          <p>{loadError}</p>
          <button type="button" onClick={() => void loadGroups()} className="mt-3 rounded-lg border border-red-500 px-3 py-2 text-sm font-bold">Try again</button>
        </div>
      ) : groups.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-stone-700 p-8 text-center">
          <p className="text-lg font-bold text-stone-200">No crossovers yet</p>
          <p className="mt-1 text-sm text-stone-500">Create one above, then add comics from dependency management.</p>
        </div>
      ) : (
        <ul className="grid gap-3" aria-label="Your crossovers">
          {groups.map((group) => {
            const isEditing = editingId === group.id
            const isBusy = busyId === group.id
            const isExpanded = expandedId === group.id
            return (
              <li key={group.id} className="rounded-2xl border border-stone-700 bg-stone-900/60 p-4">
                {isEditing ? (
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <label className="sr-only" htmlFor={`rename-${group.id}`}>Rename {group.name}</label>
                    <input
                      id={`rename-${group.id}`}
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                      className="min-w-0 flex-1 rounded-xl border border-stone-600 bg-stone-950 px-3 py-2 text-stone-100"
                      disabled={isBusy}
                    />
                    <div className="flex gap-2">
                      <button type="button" onClick={() => void saveRename(group.id)} disabled={isBusy} className="flex-1 rounded-lg bg-amber-500 px-3 py-2 text-sm font-bold text-stone-950 disabled:opacity-50">Save</button>
                      <button type="button" onClick={() => setEditingId(null)} disabled={isBusy} className="flex-1 rounded-lg border border-stone-600 px-3 py-2 text-sm font-bold text-stone-300">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <button type="button" onClick={() => setExpandedId(isExpanded ? null : group.id)} aria-expanded={isExpanded} className="min-w-0 text-left">
                      <span className="block truncate text-lg font-black text-stone-100">{group.name}</span>
                      <span className="text-sm text-stone-500">{group.memberships.length} {group.memberships.length === 1 ? 'member' : 'members'}</span>
                    </button>
                    <div className="flex gap-2">
                      <button type="button" onClick={() => beginRename(group)} disabled={isBusy} className="flex-1 rounded-lg border border-stone-600 px-3 py-2 text-sm font-bold text-stone-300 hover:border-amber-500">Rename</button>
                      <button type="button" onClick={() => void deleteGroup(group)} disabled={isBusy} className="flex-1 rounded-lg border border-red-800 px-3 py-2 text-sm font-bold text-red-400 hover:bg-red-950/40 disabled:opacity-50">Delete</button>
                    </div>
                  </div>
                )}
                {isExpanded && !isEditing && (
                  <div className="mt-4 border-t border-stone-800 pt-4 text-sm text-stone-400">
                    {group.memberships.length === 0 ? (
                      <p>This crossover has no comics yet.</p>
                    ) : (
                      <p>{group.memberships.filter((member) => member.issue_id !== null).length} issue memberships and {group.memberships.filter((member) => member.thread_id !== null).length} thread memberships.</p>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
