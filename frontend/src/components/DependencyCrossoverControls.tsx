import { useEffect, useMemo, useState } from 'react'
import {
  dependencyGroupsApi,
  type DependencyGroup,
} from '../services/api-dependency-groups'
import { getApiErrorDetail } from '../utils/apiError'

interface DependencyCrossoverControlsProps {
  sourceIssueId: number | null
  targetIssueId: number | null
  disabled?: boolean
  onMembershipChanged?: () => void
}

type CrossoverMode = 'none' | 'existing' | 'new'

export default function DependencyCrossoverControls({
  sourceIssueId,
  targetIssueId,
  disabled = false,
  onMembershipChanged,
}: DependencyCrossoverControlsProps) {
  const [mode, setMode] = useState<CrossoverMode>('none')
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [newName, setNewName] = useState('')
  const [includeSource, setIncludeSource] = useState(true)
  const [includeTarget, setIncludeTarget] = useState(true)
  const [isLoading, setIsLoading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState('')

  useEffect(() => {
    if (mode !== 'existing') return

    let isCurrent = true
    setIsLoading(true)
    setError('')
    dependencyGroupsApi
      .list()
      .then((loadedGroups) => {
        if (!isCurrent) return
        setGroups(loadedGroups)
        if (!loadedGroups.some((group) => group.id === selectedGroupId)) {
          setSelectedGroupId(null)
        }
      })
      .catch((loadError: unknown) => {
        if (!isCurrent) return
        setGroups([])
        setSelectedGroupId(null)
        setError(getApiErrorDetail(loadError))
      })
      .finally(() => {
        if (isCurrent) setIsLoading(false)
      })

    return () => {
      isCurrent = false
    }
  }, [mode, selectedGroupId])

  useEffect(() => {
    setResult('')
    setError('')
  }, [sourceIssueId, targetIssueId])

  const filteredGroups = useMemo(() => {
    const query = searchQuery.trim().toLocaleLowerCase()
    if (!query) return groups
    return groups.filter((group) => group.name.toLocaleLowerCase().includes(query))
  }, [groups, searchQuery])

  const hasSelectedMembership =
    (includeSource && sourceIssueId != null) || (includeTarget && targetIssueId != null)

  async function handleSaveMemberships() {
    if (!hasSelectedMembership) {
      setError('Select at least one issue to add to the crossover.')
      return
    }

    const normalizedName = newName.trim()
    if (mode === 'new' && !normalizedName) {
      setError('Enter a crossover name.')
      return
    }
    if (mode === 'existing' && selectedGroupId == null) {
      setError('Select an existing crossover.')
      return
    }

    setIsSaving(true)
    setError('')
    setResult('')

    let group: DependencyGroup | null = null
    const completedLabels: string[] = []
    try {
      group =
        mode === 'new'
          ? await dependencyGroupsApi.create(normalizedName)
          : groups.find((candidate) => candidate.id === selectedGroupId) ?? null

      if (!group) {
        throw new Error('The selected crossover is no longer available.')
      }

      if (includeSource && sourceIssueId != null) {
        await dependencyGroupsApi.addMember(group.id, { issue_id: sourceIssueId })
        completedLabels.push('prerequisite issue')
      }
      if (includeTarget && targetIssueId != null && targetIssueId !== sourceIssueId) {
        await dependencyGroupsApi.addMember(group.id, { issue_id: targetIssueId })
        completedLabels.push('blocked issue')
      }

      setResult(
        `${completedLabels.join(' and ')} added to ${group.name}.`,
      )
      if (mode === 'new') {
        setGroups((current) => [...current, group!])
        setSelectedGroupId(group.id)
      }
      onMembershipChanged?.()
    } catch (saveError: unknown) {
      const detail = getApiErrorDetail(saveError)
      if (group && completedLabels.length > 0) {
        setError(
          `${completedLabels.join(' and ')} added to ${group.name}, but the remaining membership failed: ${detail}`,
        )
        onMembershipChanged?.()
      } else if (group && mode === 'new') {
        setError(`Created ${group.name}, but no issue membership was added: ${detail}`)
        onMembershipChanged?.()
      } else {
        setError(detail)
      }
    } finally {
      setIsSaving(false)
    }
  }

  const controlsDisabled = disabled || isSaving

  return (
    <section className="rounded-lg border border-gray-700 bg-gray-900/60 p-3" aria-label="Crossover membership">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-gray-200">Crossover</span>
        <button
          type="button"
          className={`rounded px-2 py-1 text-xs ${mode === 'none' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300'}`}
          onClick={() => setMode('none')}
          disabled={controlsDisabled}
        >
          No membership
        </button>
        <button
          type="button"
          className={`rounded px-2 py-1 text-xs ${mode === 'existing' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300'}`}
          onClick={() => setMode('existing')}
          disabled={controlsDisabled}
        >
          Add to existing
        </button>
        <button
          type="button"
          className={`rounded px-2 py-1 text-xs ${mode === 'new' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-300'}`}
          onClick={() => setMode('new')}
          disabled={controlsDisabled}
        >
          Create crossover
        </button>
      </div>

      {mode !== 'none' && (
        <div className="mt-3 space-y-3">
          {mode === 'existing' ? (
            <>
              <label className="block text-xs text-gray-300">
                Search crossovers
                <input
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-white"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  disabled={controlsDisabled}
                />
              </label>
              <label className="block text-xs text-gray-300">
                Existing crossover
                <select
                  className="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-white"
                  value={selectedGroupId ?? ''}
                  onChange={(event) => setSelectedGroupId(Number(event.target.value) || null)}
                  disabled={controlsDisabled || isLoading}
                >
                  <option value="">{isLoading ? 'Loading…' : 'Select a crossover'}</option>
                  {filteredGroups.map((group) => (
                    <option key={group.id} value={group.id}>{group.name}</option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <label className="block text-xs text-gray-300">
              Crossover name
              <input
                className="mt-1 w-full rounded border border-gray-700 bg-gray-950 px-2 py-1 text-sm text-white"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                disabled={controlsDisabled}
                maxLength={200}
              />
            </label>
          )}

          <div className="flex flex-wrap gap-4 text-sm text-gray-200">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeSource}
                onChange={(event) => setIncludeSource(event.target.checked)}
                disabled={controlsDisabled || sourceIssueId == null}
              />
              Prerequisite issue
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeTarget}
                onChange={(event) => setIncludeTarget(event.target.checked)}
                disabled={controlsDisabled || targetIssueId == null}
              />
              Blocked issue
            </label>
          </div>

          <button
            type="button"
            className="rounded bg-purple-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            onClick={handleSaveMemberships}
            disabled={controlsDisabled || !hasSelectedMembership}
          >
            {isSaving ? 'Saving membership…' : 'Save crossover membership'}
          </button>
        </div>
      )}

      {error && <p className="mt-2 text-sm text-red-300" role="alert">{error}</p>}
      {result && <p className="mt-2 text-sm text-green-300" role="status">{result}</p>}
    </section>
  )
}
