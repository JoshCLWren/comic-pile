import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../components/continuity'
import { continuityPlansApi, type ContinuityPlanCheckpoint, type ContinuityPlanConvergenceGate, type ContinuityPlanConvergenceTarget, type ContinuityPlanNode } from '../services/api-continuity-plans'
import { dependencyGroupsApi, type DependencyGroup } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import PlanProjectionDialog from '../components/PlanProjectionDialog'
import PlanReadinessPanel from '../components/PlanReadinessPanel'
import type { Issue, Thread } from '../types'

const LAST_PLAN_KEY = 'comic-pile:last-continuity-plan'
const DEFAULT_LANE_ID = 'main'
const DEFAULT_LANE_NAME = 'Reading order'
const DEFAULT_PLAN_NAME = 'My reading plan'

interface PlannerNode extends ContinuityPlanNode {
  label: string
}

interface PlannerLane {
  id: string
  name: string
  order: number
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

function normalizePositions(nodeList: PlannerNode[]): PlannerNode[] {
  // Reassign contiguous 0-based positions per lane while preserving order.
  const byLane: Record<string, PlannerNode[]> = {}
  for (const node of nodeList) {
    ;(byLane[node.lane_id] ??= []).push(node)
  }
  const out: PlannerNode[] = []
  for (const laneId of Object.keys(byLane)) {
    const sorted = [...byLane[laneId]].sort((a, b) => a.position - b.position)
    sorted.forEach((node, index) => out.push({ ...node, position: index }))
  }
  return out
}

function buildPayload(
  name: string,
  lanes: PlannerLane[],
  nodeList: PlannerNode[],
  checkpointList: ContinuityPlanCheckpoint[],
  gateList: ContinuityPlanConvergenceGate[],
) {
  const normalized = normalizePositions(nodeList)
  const orderedLanes = [...lanes].sort((a, b) => a.order - b.order)
  const orderingMode: import('../services/api-continuity-plans').ContinuityPlanOrderingMode =
    orderedLanes.length === 1 ? 'strict_sequential' : 'informational'
  return {
    name: name.trim(),
    ordering_mode: orderingMode,
    lanes: orderedLanes.map((lane) => ({ id: lane.id, name: lane.name, order: lane.order })),
    nodes: normalized.map((node) => ({
      id: node.id,
      node_type: node.node_type,
      ref_id: node.ref_id,
      lane_id: node.lane_id,
      position: node.position,
    })),
    checkpoints: checkpointList.map((checkpoint) => ({ node_id: checkpoint.node_id })),
    convergence_gates: gateList.map((gate) => ({
      id: gate.id,
      gate_node_id: gate.gate_node_id,
      wait_for: gate.wait_for.map((target) => ({ node_id: target.node_id })),
    })),
  }
}

function laneNodeCount(nodes: PlannerNode[], laneId: string): number {
  return nodes.filter((node) => node.lane_id === laneId).length
}

export default function ContinuityPlannerPage() {
  const { id } = useParams()
  const navigate = useNavigate()
  const parsedId = id ? Number(id) : null
  const planId = parsedId && Number.isInteger(parsedId) && parsedId > 0 ? parsedId : null
  const isInvalidRoute = id !== undefined && parsedId !== null && (!Number.isInteger(parsedId) || parsedId <= 0)
  const [name, setName] = useState(DEFAULT_PLAN_NAME)
  const [lanes, setLanes] = useState<PlannerLane[]>([{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }])
  const [nodes, setNodes] = useState<PlannerNode[]>([])
  const [activeLaneId, setActiveLaneId] = useState(DEFAULT_LANE_ID)
  const [savedName, setSavedName] = useState('')
  const [savedLanes, setSavedLanes] = useState<PlannerLane[]>([])
  const [savedNodes, setSavedNodes] = useState<PlannerNode[]>([])
  const [checkpoints, setCheckpoints] = useState<ContinuityPlanCheckpoint[]>([])
  const [convergenceGates, setConvergenceGates] = useState<ContinuityPlanConvergenceGate[]>([])
  const [savedCheckpoints, setSavedCheckpoints] = useState<ContinuityPlanCheckpoint[]>([])
  const [savedConvergenceGates, setSavedConvergenceGates] = useState<ContinuityPlanConvergenceGate[]>([])
  const [gateSeq, setGateSeq] = useState(0)
  const [gateNodeSelect, setGateNodeSelect] = useState('')
  const [gateWaitSelect, setGateWaitSelect] = useState<string[]>([])
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
  const [laneSeq, setLaneSeq] = useState(0)
  const [readinessRefreshKey, setReadinessRefreshKey] = useState(0)
  const lastPlanId = typeof window === 'undefined' ? null : window.localStorage.getItem(LAST_PLAN_KEY)
  const issueRequestRef = useRef<AbortController | null>(null)

  const isDirty =
    name !== savedName ||
    JSON.stringify(lanes) !== JSON.stringify(savedLanes) ||
    JSON.stringify(nodes) !== JSON.stringify(savedNodes) ||
    JSON.stringify(checkpoints) !== JSON.stringify(savedCheckpoints) ||
    JSON.stringify(convergenceGates) !== JSON.stringify(savedConvergenceGates)

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

  const orderedLanes = [...lanes].sort((a, b) => a.order - b.order)
  const targetLaneId = orderedLanes.some((lane) => lane.id === activeLaneId)
    ? activeLaneId
    : orderedLanes[0]?.id ?? DEFAULT_LANE_ID

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
          setSavedLanes([{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }])
          setSavedNodes([])
          setActiveLaneId(DEFAULT_LANE_ID)
          return
        }
        const plan = await continuityPlansApi.get(planId)
        const loadedLanes = (plan.lanes.length > 0
          ? plan.lanes
          : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
        ).map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
          .sort((a, b) => a.order - b.order)
        const hydrated = await hydrateLabels(
          [...plan.nodes].sort((a, b) => a.position - b.position),
          loadedGroups,
        )
        const loadedCheckpoints: ContinuityPlanCheckpoint[] = (plan.checkpoints ?? []).map(
          (checkpoint) => ({ node_id: checkpoint.node_id }),
        )
        const loadedGates: ContinuityPlanConvergenceGate[] = (plan.convergence_gates ?? []).map(
          (gate) => ({
            id: gate.id,
            gate_node_id: gate.gate_node_id,
            wait_for: gate.wait_for.map((target) => ({ node_id: target.node_id })),
          }),
        )
        if (!active) return
        setName(plan.name)
        setLanes(loadedLanes)
        setNodes(normalizePositions(hydrated))
        setCheckpoints(loadedCheckpoints)
        setConvergenceGates(loadedGates)
        setSavedName(plan.name)
        setSavedLanes(loadedLanes)
        setSavedNodes(normalizePositions(hydrated))
        setSavedCheckpoints(loadedCheckpoints)
        setSavedConvergenceGates(loadedGates)
        setGateSeq(loadedGates.length)
        setActiveLaneId(loadedLanes[0]?.id ?? DEFAULT_LANE_ID)
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

  const addNode = (node: Omit<PlannerNode, 'lane_id' | 'position' | 'label'>, label: string) => {
    const laneId = targetLaneId
    const nextPosition = laneNodeCount(nodes, laneId)
    setNodes((current) =>
      normalizePositions([
        ...current,
        { ...node, lane_id: laneId, position: nextPosition, label },
      ]),
    )
  }

  const addIssue = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedThread || !selectedIssue) return
    const key = `issue-${selectedIssue.id}`
    if (nodes.some((node) => node.id === key)) {
      setSaveError('That issue is already in this plan.')
      return
    }
    addNode(
      { id: key, node_type: 'issue', ref_id: selectedIssue.id },
      `${selectedThread.title} #${selectedIssue.issue_number}`,
    )
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
    addNode({ id: key, node_type: 'crossover', ref_id: group.id }, group.name)
    setSelectedGroupId('')
    setSaveError(null)
  }

  const moveInLane = (nodeId: string, offset: -1 | 1) => {
    setNodes((current) => {
      const node = current.find((candidate) => candidate.id === nodeId)
      if (!node) return current
      const lane = current
        .filter((candidate) => candidate.lane_id === node.lane_id)
        .sort((a, b) => a.position - b.position)
      const index = lane.findIndex((candidate) => candidate.id === nodeId)
      const nextIndex = index + offset
      if (nextIndex < 0 || nextIndex >= lane.length) return current
      ;[lane[index], lane[nextIndex]] = [lane[nextIndex], lane[index]]
      const reordered = lane.map((candidate, position) => ({ ...candidate, position }))
      const others = current.filter((candidate) => candidate.lane_id !== node.lane_id)
      return normalizePositions([...others, ...reordered])
    })
  }

  const moveToLane = (nodeId: string, laneId: string) => {
    setNodes((current) => {
      const node = current.find((candidate) => candidate.id === nodeId)
      if (!node || node.lane_id === laneId) return current
      const moved = { ...node, lane_id: laneId, position: laneNodeCount(current, laneId) }
      return normalizePositions(current.map((candidate) => (candidate.id === nodeId ? moved : candidate)))
    })
  }

  const removeNode = (nodeId: string) => {
    setNodes((current) =>
      normalizePositions(current.filter((candidate) => candidate.id !== nodeId)),
    )
    setCheckpoints((current) => current.filter((checkpoint) => checkpoint.node_id !== nodeId))
    setConvergenceGates((current) =>
      current
        .filter((gate) => gate.gate_node_id !== nodeId)
        .map((gate) => ({
          ...gate,
          wait_for: gate.wait_for.filter((target) => target.node_id !== nodeId),
        }))
        .filter((gate) => gate.wait_for.length > 0),
    )
  }

  const isCheckpoint = (nodeId: string): boolean =>
    checkpoints.some((checkpoint) => checkpoint.node_id === nodeId)

  const toggleCheckpoint = (nodeId: string) => {
    setCheckpoints((current) => {
      if (current.some((checkpoint) => checkpoint.node_id === nodeId)) {
        return current.filter((checkpoint) => checkpoint.node_id !== nodeId)
      }
      return [...current, { node_id: nodeId }]
    })
  }

  const addConvergenceGate = () => {
    if (!gateNodeSelect || gateWaitSelect.length === 0) return
    if (gateWaitSelect.includes(gateNodeSelect)) {
      setSaveError('A convergence gate cannot wait for itself.')
      return
    }
    const id = `gate-${gateSeq + 1}`
    setGateSeq((currentSeq) => currentSeq + 1)
    setConvergenceGates((current) => [
      ...current,
      {
        id,
        gate_node_id: gateNodeSelect,
        wait_for: gateWaitSelect.map((nodeId) => ({ node_id: nodeId })),
      },
    ])
    setGateNodeSelect('')
    setGateWaitSelect([])
    setSaveError(null)
  }

  const removeConvergenceGate = (gateId: string) => {
    setConvergenceGates((current) => current.filter((gate) => gate.id !== gateId))
  }

  const addLane = () => {
    const id = `lane-${laneSeq + 1}`
    setLaneSeq((currentSeq) => currentSeq + 1)
    setLanes((current) => [
      ...current,
      { id, name: `Lane ${current.length + 1}`, order: current.length },
    ])
    setActiveLaneId(id)
  }

  const renameLane = (laneId: string, value: string) => {
    setLanes((current) =>
      current.map((lane) => (lane.id === laneId ? { ...lane, name: value } : lane)),
    )
  }

  const moveLane = (laneId: string, offset: -1 | 1) => {
    setLanes((current) => {
      const sorted = [...current].sort((a, b) => a.order - b.order)
      const index = sorted.findIndex((lane) => lane.id === laneId)
      const nextIndex = index + offset
      if (nextIndex < 0 || nextIndex >= sorted.length) return current
      ;[sorted[index], sorted[nextIndex]] = [sorted[nextIndex], sorted[index]]
      return sorted.map((lane, position) => ({ ...lane, order: position }))
    })
  }

  const removeLane = (laneId: string) => {
    if (laneNodeCount(nodes, laneId) > 0 || lanes.length <= 1) return
    setLanes((current) =>
      current
        .filter((lane) => lane.id !== laneId)
        .map((lane, position) => ({ ...lane, order: position })),
    )
    setActiveLaneId((current) => (current === laneId ? lanes.find((lane) => lane.id !== laneId)?.id ?? '' : current))
  }

  const save = async () => {
    if (!name.trim()) {
      setSaveError('Enter a plan name.')
      return
    }
    setIsSaving(true)
    setSaveError(null)
     try {
      const payload = buildPayload(name, lanes, nodes, checkpoints, convergenceGates)
      const saved = planId
        ? await continuityPlansApi.update(planId, payload)
        : await continuityPlansApi.create(payload)
      const savedLanes = (saved.lanes.length > 0
        ? saved.lanes
        : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
      ).map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
        .sort((a, b) => a.order - b.order)
      const normalized = normalizePositions(nodes)
      const savedCheckpoints: ContinuityPlanCheckpoint[] = (saved.checkpoints ?? []).map(
        (checkpoint) => ({ node_id: checkpoint.node_id }),
      )
      const savedGates: ContinuityPlanConvergenceGate[] = (saved.convergence_gates ?? []).map(
        (gate) => ({
          id: gate.id,
          gate_node_id: gate.gate_node_id,
          wait_for: gate.wait_for.map((target) => ({ node_id: target.node_id })),
        }),
      )
      setName(saved.name)
      setLanes(savedLanes)
      setNodes(normalized)
      setCheckpoints(savedCheckpoints)
      setConvergenceGates(savedGates)
      setSavedName(saved.name)
      setSavedLanes(savedLanes)
      setSavedNodes(normalized)
      setSavedCheckpoints(savedCheckpoints)
      setSavedConvergenceGates(savedGates)
      setGateSeq(savedGates.length)
      window.localStorage.setItem(LAST_PLAN_KEY, String(saved.id))
      setReadinessRefreshKey((key) => key + 1)
      if (!planId) navigate(`/continuity-plans/${saved.id}`, { replace: true })
    } catch (error) {
      setSaveError(errorMessage(error, 'Unable to save this continuity plan.'))
    } finally {
      setIsSaving(false)
    }
  }

  const cancel = () => {
    setName(savedName || DEFAULT_PLAN_NAME)
    setLanes(savedLanes.length > 0 ? savedLanes : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }])
    setNodes(savedNodes)
    setCheckpoints(savedCheckpoints)
    setConvergenceGates(savedConvergenceGates)
    setActiveLaneId(savedLanes[0]?.id ?? DEFAULT_LANE_ID)
    setSaveError(null)
  }

  const statusText = isSaving ? 'Saving…' : saveError ? null : isDirty ? 'Unsaved changes' : planId ? 'Saved' : 'New plan'

  if (isLoading) return <p role="status" className="text-stone-400">Loading continuity plan…</p>
  if (loadError) return <div role="alert" className="rounded-2xl border border-red-800 bg-red-950/30 p-4 text-red-200">{loadError}</div>

  const globalIndex = new Map<string, number>()
  let runningIndex = 0
  for (const lane of orderedLanes) {
    const laneNodes = nodes
      .filter((node) => node.lane_id === lane.id)
      .sort((a, b) => a.position - b.position)
    for (const node of laneNodes) {
      globalIndex.set(node.id, runningIndex)
      runningIndex += 1
    }
  }

  return (
    <section className="space-y-5" aria-labelledby="planner-heading">
      <header>
        <p className="text-xs font-black uppercase tracking-[0.2em] text-amber-500">Continuity</p>
        <h1 id="planner-heading" className="mt-1 text-3xl font-black text-stone-100">Sequential planner</h1>
        <p className="mt-2 text-sm text-stone-400">Arrange issues and crossovers in one or more parallel reading lanes. Saving creates only the continuity rules you chose.</p>
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

      <section aria-labelledby="lanes-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="lanes-heading" className="text-xl font-black text-stone-100">Reading lanes</h2>
            <p className="text-xs text-stone-500">{orderedLanes.length} {orderedLanes.length === 1 ? 'lane' : 'lanes'} · {nodes.length} {nodes.length === 1 ? 'step' : 'steps'}</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={addLane} className="min-h-11 rounded-xl border border-stone-700 px-3 font-bold text-stone-100">
              Add lane
            </button>
            {planId && (
              <button type="button" onClick={() => setIsProjectionOpen(true)} className="min-h-11 rounded-xl border border-amber-700 px-4 font-bold text-amber-200">
                Project to reading order
              </button>
            )}
            {statusText && <p role="status" className={isDirty ? 'text-amber-300' : 'text-emerald-300'}>{statusText}</p>}
          </div>
        </div>

        {orderedLanes.length > 1 && (
          <label className="mt-3 block text-xs font-bold uppercase tracking-widest text-stone-500 md:hidden">
            Viewing lane
            <select
              value={targetLaneId}
              onChange={(event) => setActiveLaneId(event.target.value)}
              className="mt-1 min-h-11 w-full rounded-xl border border-stone-700 bg-stone-950 px-3 text-stone-100"
            >
              {orderedLanes.map((lane) => (
                <option key={lane.id} value={lane.id}>{lane.name}</option>
              ))}
            </select>
          </label>
        )}

        <div className="mt-3 space-y-4">
          {orderedLanes.map((lane) => {
            const laneNodes = nodes
              .filter((node) => node.lane_id === lane.id)
              .sort((a, b) => a.position - b.position)
            const isMobileHidden = orderedLanes.length > 1 && lane.id !== targetLaneId
            return (
              <div
                key={lane.id}
                data-testid={`lane-${lane.id}`}
                className={`rounded-2xl border border-stone-800 bg-stone-900/40 p-4 ${isMobileHidden ? 'hidden' : 'block'} md:block`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <input
                    value={lane.name}
                    onChange={(event) => renameLane(lane.id, event.target.value)}
                    maxLength={120}
                    aria-label={`Lane ${lane.name} name`}
                    className="min-w-[10rem] flex-1 rounded-xl border border-stone-700 bg-stone-950 px-3 py-2 font-bold text-stone-100"
                  />
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => moveLane(lane.id, -1)}
                      disabled={lane.order === 0}
                      aria-label={`Move lane ${lane.name} earlier`}
                      className="min-h-9 min-w-9 rounded-lg border border-stone-700 disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => moveLane(lane.id, 1)}
                      disabled={lane.order === orderedLanes.length - 1}
                      aria-label={`Move lane ${lane.name} later`}
                      className="min-h-9 min-w-9 rounded-lg border border-stone-700 disabled:opacity-30"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      onClick={() => removeLane(lane.id)}
                      disabled={laneNodeCount(nodes, lane.id) > 0 || lanes.length <= 1}
                      aria-label={`Remove lane ${lane.name}`}
                      title={laneNodeCount(nodes, lane.id) > 0 ? 'Move all steps out of this lane before removing it' : undefined}
                      className="min-h-9 rounded-lg border border-red-900 px-3 text-red-300 disabled:opacity-30"
                    >
                      Remove
                    </button>
                  </div>
                </div>
                {laneNodeCount(nodes, lane.id) > 0 ? (
                  <ol className="mt-3 grid gap-2">
                    {laneNodes.map((node) => {
                      const index = laneNodes.findIndex((candidate) => candidate.id === node.id)
                      const otherLanes = orderedLanes.filter((candidate) => candidate.id !== lane.id)
                      return (
                        <li key={node.id} data-testid={`lane-item-${globalIndex.get(node.id)}`} className="flex items-center gap-3 rounded-2xl border border-stone-700 bg-stone-900 p-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-stone-800 font-black text-amber-300">{index + 1}</span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-bold text-stone-100">{node.label}</p>
                            <p className="text-xs uppercase tracking-wider text-stone-500">{node.node_type}</p>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {otherLanes.length > 0 && (
                              <select
                                aria-label={`Move ${node.label} to another lane`}
                                value={node.lane_id}
                                onChange={(event) => moveToLane(node.id, event.target.value)}
                                className="min-h-11 rounded-lg border border-stone-700 bg-stone-950 px-2 text-stone-100"
                              >
                                <option value={node.lane_id}>In {lane.name}</option>
                                {otherLanes.map((target) => (
                                  <option key={target.id} value={target.id}>→ {target.name}</option>
                                ))}
                              </select>
                            )}
                            <button type="button" onClick={() => moveInLane(node.id, -1)} disabled={index === 0} aria-label={`Move ${node.label} earlier`} className="min-h-11 min-w-11 rounded-lg border border-stone-700 disabled:opacity-30">↑</button>
                            <button type="button" onClick={() => moveInLane(node.id, 1)} disabled={index === laneNodes.length - 1} aria-label={`Move ${node.label} later`} className="min-h-11 min-w-11 rounded-lg border border-stone-700 disabled:opacity-30">↓</button>
                            {node.node_type === 'issue' && (
                              <button
                                type="button"
                                onClick={() => toggleCheckpoint(node.id)}
                                aria-pressed={isCheckpoint(node.id)}
                                aria-label={`Mark ${node.label} as a checkpoint`}
                                data-testid={`checkpoint-toggle-${node.id}`}
                                className={`min-h-11 rounded-lg border px-3 ${
                                  isCheckpoint(node.id)
                                    ? 'border-amber-500 bg-amber-500/20 text-amber-200'
                                    : 'border-stone-700 text-stone-300'
                                }`}
                              >
                                {isCheckpoint(node.id) ? 'Checkpoint' : 'Set checkpoint'}
                              </button>
                            )}
                            <button type="button" onClick={() => removeNode(node.id)} aria-label={`Remove ${node.label}`} className="min-h-11 rounded-lg border border-red-900 px-3 text-red-300">Remove</button>
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                ) : (
                  <p className="mt-3 rounded-2xl border border-dashed border-stone-700 p-4 text-center text-stone-500">No steps in this lane yet.</p>
                )}
              </div>
            )
          })}
        </div>
      </section>

      <section aria-labelledby="convergence-gates-heading" className="rounded-2xl border border-stone-800 bg-stone-900/40 p-4">
        <h2 id="convergence-gates-heading" className="text-xl font-black text-stone-100">Convergence gates</h2>
        <p className="text-xs text-stone-500">
          A convergence gate keeps one step blocked until every selected step is read. This compiles through the same continuity engine as raw rules.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="space-y-2">
            <h3 className="font-bold text-stone-200">Add a gate</h3>
            <label className="block text-xs font-bold uppercase tracking-widest text-stone-500">
              Gate step
              <select
                value={gateNodeSelect}
                onChange={(event) => setGateNodeSelect(event.target.value)}
                data-testid="gate-node-select"
                className="mt-1 min-h-11 w-full rounded-xl border border-stone-700 bg-stone-950 px-3 text-stone-100"
              >
                <option value="">Select the step to gate</option>
                {nodes.map((node) => (
                  <option key={node.id} value={node.id} disabled={node.node_type === 'thread'}>
                    {node.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs font-bold uppercase tracking-widest text-stone-500">
              Wait for
              <select
                multiple
                value={gateWaitSelect}
                onChange={(event) =>
                  setGateWaitSelect(
                    Array.from(event.target.selectedOptions).map((option) => option.value),
                  )
                }
                data-testid="gate-wait-select"
                className="mt-1 min-h-[6rem] w-full rounded-xl border border-stone-700 bg-stone-950 px-3 py-2 text-stone-100"
              >
                {nodes.map((node) => (
                  <option key={node.id} value={node.id} disabled={node.node_type === 'thread'}>
                    {node.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={addConvergenceGate}
              disabled={!gateNodeSelect || gateWaitSelect.length === 0}
              className="min-h-11 w-full rounded-xl bg-violet-500 px-4 font-black text-stone-950 disabled:opacity-50"
            >
              Add convergence gate
            </button>
          </div>
          <div className="space-y-2">
            <h3 className="font-bold text-stone-200">Active gates</h3>
            {convergenceGates.length === 0 ? (
              <p className="rounded-2xl border border-dashed border-stone-700 p-4 text-center text-stone-500">No convergence gates yet.</p>
            ) : (
              <ul className="grid gap-2">
                {convergenceGates.map((gate) => (
                  <li
                    key={gate.id}
                    data-testid={`convergence-gate-${gate.id}`}
                    className="flex flex-wrap items-center gap-2 rounded-2xl border border-violet-900/50 bg-stone-900 p-3"
                  >
                    <span className="flex-1 text-sm font-bold text-stone-100">
                      {nodes.find((node) => node.id === gate.gate_node_id)?.label ?? gate.gate_node_id} waits for{' '}
                      {gate.wait_for
                        .map((target) => nodes.find((node) => node.id === target.node_id)?.label ?? target.node_id)
                        .join(', ')}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeConvergenceGate(gate.id)}
                      aria-label={`Remove gate ${gate.id}`}
                      className="min-h-9 rounded-lg border border-red-900 px-3 text-red-300"
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>

      <PlanReadinessPanel planId={planId} refreshKey={readinessRefreshKey} />

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
