import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../components/continuity'
import { continuityPlansApi, type ContinuityPlanNode } from '../services/api-continuity-plans'
import { dependencyGroupsApi, type DependencyGroup } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import PlanProjectionDialog from '../components/PlanProjectionDialog'
import type { Issue, Thread } from '../types'

const LAST_PLAN_KEY = 'comic-pile:last-continuity-plan'
const DEFAULT_PLAN_NAME = 'My reading plan'
const DEFAULT_LANE = { id: 'main', name: 'Reading order', order: 0 }

interface LaneState {
  id: string
  name: string
  order: number
}

interface PlannerNode extends ContinuityPlanNode {
  label: string
}

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (detail && typeof detail === 'object' && 'code' in detail) {
      if (detail.code === 'plan_rule_conflict') {
        return 'This order conflicts with an existing continuity rule. Change the sequence and try again.'
      }
      if (detail.code === 'continuity_cycle') {
        return 'This order would create a continuity cycle. Change the sequence and try again.'
      }
    }
  }
  return error instanceof Error && error.message ? error.message : fallback
}

async function fetchAllThreads(): Promise<Thread[]> {
  const result: Thread[] = []
  const seen = new Set<string>()
  let token: string | null = null
  do {
    const page = await threadsApi.list({ page_size: 100 }, token)
    result.push(...page.threads)
    token = page.next_page_token
    if (token && seen.has(token)) break
    if (token) seen.add(token)
  } while (token)
  return result
}

async function fetchAllIssues(threadId: number): Promise<Issue[]> {
  const result: Issue[] = []
  const seen = new Set<string>()
  let token: string | null = null
  do {
    const page = await issuesApi.list(threadId, {
      page_size: 100,
      ...(token ? { page_token: token } : {}),
    })
    result.push(...page.issues)
    token = page.next_page_token
    if (token && seen.has(token)) break
    if (token) seen.add(token)
  } while (token)
  return result
}

function toPayload(name: string, lanes: LaneState[], nodes: PlannerNode[]) {
  return {
    name: name.trim(),
    ordering_mode: 'informational' as const,
    lanes: lanes.map((lane) => ({ id: lane.id, name: lane.name, order: lane.order })),
    nodes: nodes.map(({ id, node_type, ref_id, lane_id }, position) => ({
      id,
      node_type,
      ref_id,
      lane_id: lane_id || lanes[0]?.id || 'main',
      position,
    })),
  }
}

export default function ContinuityPlannerPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const parsedId = id ? Number(id) : null
  const planId = parsedId && Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null
  const isInvalidRoute = id !== undefined && parsedId !== null && (!Number.isInteger(parsedId) || parsedId <= 0)
  const [name, setName] = useState(DEFAULT_PLAN_NAME)
  const [nodes, setNodes] = useState<PlannerNode[]>([])
  const [savedName, setSavedName] = useState('')
  const [savedNodes, setSavedNodes] = useState<PlannerNode[]>([])
  const [threads, setThreads] = useState<Thread[]>([])
  const [groups, setGroups] = useState<DependencyGroup[]>([])
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [isLoading, setIsLoading] = useState(Boolean(planId))
  const [isLoadingIssues, setIsLoadingIssues] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [issueLoadError, setIssueLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isProjectionOpen, setIsProjectionOpen] = useState(false)
  const lastPlanId = typeof window === 'undefined' ? null : window.localStorage.getItem(LAST_PLAN_KEY)
  const issueRequestRef = useRef<AbortController | null>(null)

  const isDirty = name !== savedName || JSON.stringify(nodes) !== JSON.stringify(savedNodes) || JSON.stringify(lanes) !== JSON.stringify(savedLanes)

  const hydrateLabels = useCallback(async (rawNodes: ContinuityPlanNode[], loadedGroups: DependencyGroup[]) => {
    const groupNames = new Map(loadedGroups.map((group) => [group.id, group.name]))
    return Promise.all(rawNodes.map(async (node): Promise<PlannerNode> => {
      if (node.node_type === 'crossover') {
        return { ...node, label: groupNames.get(node.ref_id) ?? 'Unavailable crossover' }
      }
      try {
        const issue = await issuesApi.get(node.ref_id)
        const thread = await threadsApi.get(issue.thread_id)
        return { ...node, label: `${thread.title} #${issue.issue_number}` }
      } catch {
        return { ...node, label: 'Unavailable issue' }
      }
    }))
  }, [])

  useEffect(() => {
    let active = true
    void Promise.all([fetchAllThreads(), dependencyGroupsApi.list()])
      .then(async ([loadedThreads, loadedGroups]) => {
        if (!active) return
        setThreads(loadedThreads)
        setGroups(loadedGroups)
        if (isInvalidRoute) {
          active && setLoadError('Invalid continuity plan ID.')
          active && setIsLoading(false)
          return
        }
        if (!planId) {
          setSavedName(DEFAULT_PLAN_NAME)
          return
        }
        const plan = await continuityPlansApi.get(planId)
        const orderedNodes = [...plan.nodes].sort((a, b) => a.position - b.position)
        const hydrated = await hydrateLabels(orderedNodes, loadedGroups)
        if (!active) return
        setName(plan.name)
        setLanes(plan.lanes || [DEFAULT_LANE])
        setSelectedLaneId((plan.lanes && plan.lanes[0]?.id) ? plan.lanes[0].id : DEFAULT_LANE.id)
        setNodes(hydrated)
        setSavedName(plan.name)
        setSavedNodes(hydrated)
        setSavedLanes(plan.lanes || [DEFAULT_LANE])
        window.localStorage.setItem(LAST_PLAN_KEY, String(plan.id))
      })
      .catch((error) => active && setLoadError(errorMessage(error, 'Unable to load the continuity planner.')))
      .finally(() => active && setIsLoading(false))
    return () => { active = false }
  }, [hydrateLabels, planId, isInvalidRoute])

  const selectThread = async (thread: Thread | null) => {
    setSelectedThread(thread)
    setSelectedIssue(null)
    setIssues([])
    setIssueLoadError(null)
    if (!thread) {
      setIsLoadingIssues(false)
      return
    }
    if (issueRequestRef.current) issueRequestRef.current.abort()
    const controller = new AbortController()
    issueRequestRef.current = controller
    setIsLoadingIssues(true)
    try {
      const loadedIssues = await fetchAllIssues(thread.id)
      if (controller.signal.aborted) return
      setIssues(loadedIssues)
    } catch (error) {
      if (controller.signal.aborted) return
      setIssueLoadError(errorMessage(error, 'Unable to load issues for that comic.'))
    } finally {
      if (!controller.signal.aborted) setIsLoadingIssues(false)
    }
  }

  const addIssue = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedThread || !selectedIssue) return
    const key = `issue-${selectedIssue.id}`
    if (nodes.some((node) => node.id === key)) {
      setSaveError('That issue is already in this plan.')
      return
    }
    setNodes((current) => [...current, {
      id: key,
      node_type: 'issue',
      ref_id: selectedIssue.id,
      lane_id: selectedLaneId,
      position: current.length,
      label: `${selectedThread.title} #${selectedIssue.issue_number}`,
    }])
    setSelectedIssue(null)
    setSaveError(null)
  }

  const addCrossover = () => {
    const group = groups.find((candidate) => candidate.id === Number(selectedGroupId))
    if (!group) return
    const key = `crossover-${group.id}`
    if (nodes.some((node) => node.id === key)) {
      setSaveError('That crossover is already in this plan.')
      return
    }
    setNodes((current) => [...current, {
      id: key,
      node_type: 'crossover',
      ref_id: group.id,
      lane_id: selectedLaneId,
      position: current.length,
      label: group.name,
    }])
    setSelectedGroupId('')
    setSaveError(null)
  }

  const move = (index: number, offset: -1 | 1) => {
    const nextIndex = index + offset
    if (nextIndex < 0 || nextIndex >= nodes.length) return
    setNodes((current) => {
      const next = [...current]
      ;[next[index], next[nextIndex]] = [next[nextIndex], next[index]]
      return next.map((node, position) => ({ ...node, position }))
    })
  }

  const save = async () => {
    if (!name.trim()) {
      setSaveError('Enter a plan name.')
      return
    }
    setIsSaving(true)
    setSaveError(null)
    try {
      const saved = planId
        ? await continuityPlansApi.update(planId, toPayload(name, lanes, nodes))
        : await continuityPlansApi.create(toPayload(name, lanes, nodes))
      const normalized = nodes.map((node, position) => ({ ...node, position }))
      setNodes(normalized)
      setSavedName(saved.name)
      setSavedNodes(normalized)
      window.localStorage.setItem(LAST_PLAN_KEY, String(saved.id))
      if (!planId) navigate(`/continuity-plans/${saved.id}`, { replace: true })
    } catch (error) {
      setSaveError(errorMessage(error, 'Unable to save this continuity plan.'))
    } finally {
      setIsSaving(false)
    }
  }

  const cancel = () => {
    setName(savedName || DEFAULT_PLAN_NAME)
    setLanes(savedLanes)
    setSelectedLaneId(savedLanes[0]?.id || DEFAULT_LANE.id)
    setNodes(savedNodes)
    setSaveError(null)
  }

  const statusText = isSaving ? 'Saving…' : saveError ? null : isDirty ? 'Unsaved changes' : planId ? 'Saved' : 'New plan'

  if (isLoading) return <p role="status" className="text-stone-400">Loading continuity plan…</p>
  if (loadError) return <div role="alert" className="rounded-2xl border border-red-800 bg-red-950/30 p-4 text-red-200">{loadError}</div>

  return (
    <section className="space-y-5" aria-labelledby="planner-heading">
      <header>
        <p className="text-xs font-black uppercase tracking-[0.2em] text-amber-500">Continuity</p>
        <h1 id="planner-heading" className="mt-1 text-3xl font-black text-stone-100">Sequential planner</h1>
        <p className="mt-2 text-sm text-stone-400">Arrange issues and crossovers in one explicit reading lane. Saving creates only the continuity rules you chose.</p>
      </header>

      {!planId && lastPlanId && (
        <button type="button" onClick={() => navigate(`/continuity-plans/${lastPlanId}`)} className="min-h-11 rounded-xl border border-amber-700 px-4 font-bold text-amber-200">
          Reopen last saved plan
        </button>
      )}

      <label className="block text-xs font-bold uppercase tracking-widest text-stone-500">
        Plan name
        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} className="mt-1 w-full rounded-xl border border-stone-700 bg-stone-950 px-3 py-3 text-stone-100" />
      </label>

      <div className="grid gap-4 rounded-2xl border border-stone-800 bg-stone-900/50 p-4 md:grid-cols-2">
        <form onSubmit={addIssue} className="space-y-3" aria-label="Add an issue">
          <h2 className="font-black text-stone-100">Add an issue</h2>
          <ContinuityThreadSelector threads={threads} value={selectedThread} onChange={(thread) => void selectThread(thread)} label="Comic series" />
          <ContinuityIssueSelector issues={issues} value={selectedIssue} onChange={setSelectedIssue} isLoading={isLoadingIssues} disabled={!selectedThread} error={issueLoadError} />
          <button type="submit" disabled={!selectedIssue} className="min-h-11 w-full rounded-xl bg-amber-500 px-4 font-black text-stone-950 disabled:opacity-50">Add issue</button>
        </form>

        <div className="space-y-3">
          <h2 className="font-black text-stone-100">Add a crossover</h2>
          <label className="block text-xs font-bold uppercase tracking-widest text-stone-500">
            Crossover
            <select value={selectedGroupId} onChange={(event) => setSelectedGroupId(event.target.value)} className="mt-1 min-h-11 w-full rounded-xl border border-stone-700 bg-stone-950 px-3 text-stone-100">
              <option value="">Select a crossover</option>
              {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </select>
          </label>
          <button type="button" onClick={addCrossover} disabled={!selectedGroupId} className="min-h-11 w-full rounded-xl bg-violet-500 px-4 font-black text-stone-950 disabled:opacity-50">Add crossover</button>
        </div>
      </div>

      <section aria-labelledby="lane-heading">
        <div className="flex items-end justify-between">
          <div>
            <h2 id="lane-heading" className="text-xl font-black text-stone-100">Reading order</h2>
            <p className="text-xs text-stone-500">{nodes.length} {nodes.length === 1 ? 'step' : 'steps'}</p>
          </div>
          <div className="flex items-center gap-2">
            {planId && (
              <button type="button" onClick={() => setIsProjectionOpen(true)} className="min-h-11 rounded-xl border border-amber-700 px-4 font-bold text-amber-200">
                Project to reading order
              </button>
            )}
            {statusText && <p role="status" className={isDirty ? 'text-amber-300' : 'text-emerald-300'}>{statusText}</p>}
          </div>
        </div>
        {nodes.length === 0 ? (
          <p className="mt-3 rounded-2xl border border-dashed border-stone-700 p-6 text-center text-stone-500">Add an issue or crossover to begin.</p>
        ) : (
          <ol className="mt-3 grid gap-2">
            {nodes.map((node, index) => (
              <li key={node.id} data-testid={`lane-item-${index}`} className="flex items-center gap-3 rounded-2xl border border-stone-700 bg-stone-900 p-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-stone-800 font-black text-amber-300">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate font-bold text-stone-100">{node.label}</p>
                  <p className="text-xs uppercase tracking-wider text-stone-500">{node.node_type}</p>
                </div>
                <div className="flex gap-1">
                  <button type="button" onClick={() => move(index, -1)} disabled={index === 0} aria-label={`Move ${node.label} earlier`} className="min-h-11 min-w-11 rounded-lg border border-stone-700 disabled:opacity-30">↑</button>
                  <button type="button" onClick={() => move(index, 1)} disabled={index === nodes.length - 1} aria-label={`Move ${node.label} later`} className="min-h-11 min-w-11 rounded-lg border border-stone-700 disabled:opacity-30">↓</button>
                  <button type="button" onClick={() => setNodes((current) => current.filter((item) => item.id !== node.id).map((item, position) => ({ ...item, position })))} aria-label={`Remove ${node.label}`} className="min-h-11 rounded-lg border border-red-900 px-3 text-red-300">Remove</button>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>

      {saveError && <p role="alert" className="rounded-xl border border-red-800 bg-red-950/30 p-3 text-red-200">{saveError}</p>}
      <div className="sticky bottom-16 flex gap-3 rounded-2xl border border-stone-800 bg-stone-950/95 p-3 backdrop-blur md:bottom-24">
        <button type="button" onClick={cancel} disabled={!isDirty || isSaving} className="min-h-11 flex-1 rounded-xl border border-stone-700 font-bold disabled:opacity-40">Cancel changes</button>
        <button type="button" onClick={() => void save()} disabled={!isDirty || isSaving} className="min-h-11 flex-1 rounded-xl bg-amber-500 font-black text-stone-950 disabled:opacity-40">{isSaving ? 'Saving…' : 'Save plan'}</button>
      </div>

      {planId && (
        <PlanProjectionDialog
          isOpen={isProjectionOpen}
          planId={planId}
          planName={savedName || name}
          onClose={() => setIsProjectionOpen(false)}
        />
      )}
    </section>
  )
}
