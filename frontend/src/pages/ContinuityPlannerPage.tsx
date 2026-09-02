import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ContinuityIssueSelector,
  ContinuityThreadSelector,
} from '../components/continuity'
import { continuityPlansApi, type ContinuityPlanNode, type ContinuityPlanNodeType, type ContinuityPlanOrderingMode } from '../services/api-continuity-plans'
import { dependencyGroupsApi, type DependencyGroup } from '../services/api-dependency-groups'
import { issuesApi } from '../services/api-issues'
import { threadsApi } from '../services/api'
import PlanProjectionDialog from '../components/PlanProjectionDialog'
import GlossaryLink from '../components/GlossaryLink'
import type { Issue, Thread } from '../types'

const LAST_PLAN_KEY = 'comic-pile:last-continuity-plan'
const DEFAULT_LANE_ID = 'main'
const DEFAULT_LANE_NAME = 'Reading order'
const DEFAULT_PLAN_NAME = 'My reading plan'

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return error instanceof Error && error.message ? error.message : fallback
}

interface PlannerNode extends ContinuityPlanNode {
  label: string
  is_checkpoint?: boolean
  convergence_gate?: Array<{ node_type: ContinuityPlanNodeType; node_id: string }>
}

interface PlannerLane {
  id: string
  name: string
  order: number
}

interface ConflictDetail {
  code?: string
  source_node_id?: string
  target_node_id?: string
}

function getConflictMessage(
  error: unknown,
  nodes: PlannerNode[]
): string {
  if (!axios.isAxiosError(error)) {
    return error instanceof Error && error.message ? error.message : 'Unable to save this continuity plan.'
  }

  const detail = error.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }

  if (detail && typeof detail === 'object' && 'code' in detail) {
    const conflict = detail as ConflictDetail
    if (conflict.code === 'plan_rule_conflict' || conflict.code === 'continuity_cycle') {
      const sourceId = conflict.source_node_id
      const targetId = conflict.target_node_id

      if (sourceId !== undefined && targetId !== undefined) {
        const sourceNode = nodes.find((node) => node.id === sourceId)
        const targetNode = nodes.find((node) => node.id === targetId)

        if (sourceNode && targetNode) {
          if (conflict.code === 'plan_rule_conflict') {
            return `You already require "${sourceNode.label}" before "${targetNode.label}". Change the sequence to resolve this conflict.`
          }
          return `This order would create a continuity cycle: "${sourceNode.label}" → "${targetNode.label}". Change the sequence to resolve this cycle.`
        }
      }

      if (conflict.code === 'plan_rule_conflict') {
        return 'This order conflicts with an existing continuity rule. Change the sequence and try again.'
      }
      return 'This order would create a continuity cycle. Change the sequence and try again.'
    }
  }

  return error instanceof Error && error.message ? error.message : 'Unable to save this continuity plan.'
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

function buildPayload(name: string, lanes: PlannerLane[], nodeList: PlannerNode[]) {
  const normalized = normalizePositions(nodeList)
  const orderedLanes = [...lanes].sort((a, b) => a.order - b.order)
  const orderingMode: ContinuityPlanOrderingMode =
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
      label: node.label ?? null,
      is_checkpoint: node.is_checkpoint ?? false,
      convergence_gate: node.convergence_gate ?? [],
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
  const [editingGateNodeId, setEditingGateNodeId] = useState<string | null>(null)
  const lastPlanId = typeof window === 'undefined' ? null : window.localStorage.getItem(LAST_PLAN_KEY)
  const issueRequestRef = useRef<AbortController | null>(null)

  const isDirty =
    name !== savedName ||
    JSON.stringify(lanes) !== JSON.stringify(savedLanes) ||
    JSON.stringify(nodes) !== JSON.stringify(savedNodes)

  const hydrateLabels = useCallback((rawNodes: ContinuityPlanNode[], loadedGroups: DependencyGroup[]): PlannerNode[] => {
    const groupNames = new Map(loadedGroups.map((group) => [group.id, group.name]))
    return rawNodes.map((node): PlannerNode => {
      const stored = typeof (node as PlannerNode).label === 'string' ? (node as PlannerNode).label.trim() : ''
      if (node.node_type === 'crossover') {
        if (stored) return { ...(node as PlannerNode), label: stored }
        return { ...(node as PlannerNode), label: groupNames.get(node.ref_id) ?? '[deleted crossover]' }
      }
      if (node.node_type === 'thread') {
        if (stored) return { ...(node as PlannerNode), label: stored }
        return { ...(node as PlannerNode), label: '[deleted series]' }
      }
      // issue nodes: prefer persisted denormalized title, no per-issue GETs that 404
      if (stored) return { ...(node as PlannerNode), label: stored }
      return { ...(node as PlannerNode), label: '[deleted series]' }
    })
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
        let hydrated = hydrateLabels(
          [...plan.nodes].sort((a, b) => a.position - b.position),
          loadedGroups,
        )
        // For legacy plans without denormalized titles, batch-hydrate via readiness (one request, no per-issue 404s).
        const needsBatch = hydrated.some(
          (node) => node.label === '[deleted series]' || node.label === '[deleted crossover]',
        )
        if (needsBatch) {
          try {
            const readiness = await continuityPlansApi.readiness(plan.id)
            const labelMap = new Map(readiness.nodes.map((item) => [item.node_id, item.label] as const))
            hydrated = hydrated.map((node) => {
              const batchLabel = labelMap.get(node.id)
              return batchLabel ? { ...node, label: batchLabel } : node
            })
          } catch {
            // Keep placeholder labels; never issue per-missing-issue GETs.
          }
        }
        if (!active) return
        setName(plan.name)
        setLanes(loadedLanes)
        setNodes(normalizePositions(hydrated))
        setSavedName(plan.name)
        setSavedLanes(loadedLanes)
        setSavedNodes(normalizePositions(hydrated))
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
  }

  const toggleCheckpoint = (nodeId: string) => {
    setNodes((current) =>
      current.map((node) =>
        node.id === nodeId ? { ...node, is_checkpoint: !node.is_checkpoint } : node,
      ),
    )
  }

  const toggleConvergenceGate = (nodeId: string, targetNodeId: string) => {
    setNodes((current) =>
      current.map((node) => {
        if (node.id !== nodeId) return node
        const gate = node.convergence_gate ?? []
        const exists = gate.some((target) => target.node_id === targetNodeId)
        const targetNode = current.find((n) => n.id === targetNodeId)!
        const updated = exists
          ? gate.filter((target) => target.node_id !== targetNodeId)
          : [...gate, { node_type: targetNode.node_type as ContinuityPlanNodeType, node_id: targetNodeId }]
        return { ...node, convergence_gate: updated }
      }),
    )
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
    if (laneNodeCount(nodes, laneId) > 0) return
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
      const payload = buildPayload(name, lanes, nodes)
      const saved = planId
        ? await continuityPlansApi.update(planId, payload)
        : await continuityPlansApi.create(payload)
      const savedLanes = (saved.lanes.length > 0
        ? saved.lanes
        : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
      ).map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
        .sort((a, b) => a.order - b.order)
      const normalized = normalizePositions(nodes)
      setName(saved.name)
      setLanes(savedLanes)
      setNodes(normalized)
      setSavedName(saved.name)
      setSavedLanes(savedLanes)
      setSavedNodes(normalized)
      window.localStorage.setItem(LAST_PLAN_KEY, String(saved.id))
      if (!planId) navigate(`/continuity-plans/${saved.id}`, { replace: true })
    } catch (error) {
      setSaveError(getConflictMessage(error, nodes))
    } finally {
      setIsSaving(false)
    }
  }

  const cancel = () => {
    setName(savedName || DEFAULT_PLAN_NAME)
    setLanes(savedLanes.length > 0 ? savedLanes : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }])
    setNodes(savedNodes)
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
    <section className="space-y-6 pb-8" aria-labelledby="planner-heading">
      <header>
        <p className="text-xs font-black uppercase tracking-[0.2em] text-[var(--theme-text-muted)]">Continuity</p>
        <h1 id="planner-heading" className="mt-1 text-3xl font-black text-[var(--theme-text-primary)]">Sequential planner</h1>
        <p className="mt-2 text-sm text-[var(--theme-text-muted)]">
          Arrange issues and crossovers in one or more parallel reading lanes. Saving creates only the continuity rules you chose.{' '}
          <GlossaryLink id="continuity-plan">Continuity Plan</GlossaryLink>,{' '}
          <GlossaryLink id="lane">Lane</GlossaryLink>, and{' '}
          <GlossaryLink id="crossover">Crossover</GlossaryLink> definitions.
        </p>
      </header>

      {!planId && lastPlanId && (
        <button type="button" onClick={() => navigate(`/continuity-plans/${lastPlanId}`)} className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]">
          Reopen last saved plan
        </button>
      )}

      <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
        Plan name
        <input value={name} onChange={(event) => setName(event.target.value)} maxLength={200} className="mt-1 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-3 text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]" />
      </label>

      <section aria-labelledby="add-steps-heading" className="border-t border-[var(--theme-border)] pt-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="add-steps-heading" className="text-xs font-black uppercase tracking-widest text-[var(--theme-text-primary)]">Add steps</h2>
          <p className="text-xs text-[var(--theme-text-muted)]">
            {orderedLanes.length === 0 ? 'Add a lane first' : `To ${orderedLanes.find((lane) => lane.id === targetLaneId)?.name ?? orderedLanes[0]?.name ?? 'lane'} · issue or crossover`}
          </p>
        </div>
        <div className="mt-4 grid gap-6 md:grid-cols-2 md:divide-x md:divide-[var(--theme-border)]">
          <form onSubmit={addIssue} className="space-y-3 md:pr-6" aria-label="Add an issue">
            <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">Issue</h3>
            <ContinuityThreadSelector threads={threads} value={selectedThread} onChange={(thread) => void selectThread(thread)} label="Comic series" />
            <ContinuityIssueSelector issues={issues} value={selectedIssue} onChange={setSelectedIssue} isLoading={isLoadingIssues} disabled={!selectedThread || orderedLanes.length === 0} error={issueLoadError} />
            <button type="submit" disabled={!selectedIssue || orderedLanes.length === 0} className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)] disabled:opacity-50">Add issue</button>
            {orderedLanes.length === 0 && <p className="text-xs text-[var(--theme-text-muted)]">Add a lane first to add issues.</p>}
          </form>

          <div className="space-y-3 border-t border-[var(--theme-border)] pt-6 md:border-t-0 md:pt-0 md:pl-6">
            <h3 className="text-sm font-bold text-[var(--theme-text-primary)]">Crossover</h3>
            <label className="block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)]">
              Crossover
              <select value={selectedGroupId} onChange={(event) => setSelectedGroupId(event.target.value)} className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]" disabled={orderedLanes.length === 0}>
                <option value="">Select a crossover</option>
                {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
              </select>
            </label>
            <button type="button" onClick={addCrossover} disabled={!selectedGroupId || orderedLanes.length === 0} className="min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-4 font-bold text-[var(--theme-text-primary)] hover:bg-[var(--theme-bg-panel)] disabled:opacity-50">Add crossover</button>
            {orderedLanes.length === 0 && <p className="text-xs text-[var(--theme-text-muted)]">Add a lane first to add crossovers.</p>}
          </div>
        </div>
      </section>

      <section aria-labelledby="lanes-heading" className="border-t border-[var(--theme-border)] pt-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="lanes-heading" className="text-sm font-black uppercase tracking-widest text-[var(--theme-text-primary)]">Reading lanes</h2>
            <p className="text-xs text-[var(--theme-text-muted)]">{orderedLanes.length} {orderedLanes.length === 1 ? 'lane' : 'lanes'} · {nodes.length} {nodes.length === 1 ? 'step' : 'steps'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={addLane} className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-transparent px-3 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]">
              Add lane
            </button>
            {planId && (
              <button type="button" onClick={() => setIsProjectionOpen(true)} className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-transparent px-3 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]">
                Project to reading order
              </button>
            )}
          </div>
        </div>

        {orderedLanes.length > 1 && (
          <label className="mt-3 block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)] md:hidden">
            Viewing lane
            <select
              value={targetLaneId}
              onChange={(event) => setActiveLaneId(event.target.value)}
              className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)]"
            >
              {orderedLanes.map((lane) => (
                <option key={lane.id} value={lane.id}>{lane.name}</option>
              ))}
            </select>
          </label>
        )}

        <div className="mt-4 space-y-6">
          {orderedLanes.map((lane) => {
            const laneNodes = nodes
              .filter((node) => node.lane_id === lane.id)
              .sort((a, b) => a.position - b.position)
            const isMobileHidden = orderedLanes.length > 1 && lane.id !== targetLaneId
            return (
              <div
                key={lane.id}
                data-testid={`lane-${lane.id}`}
                className={`${isMobileHidden ? 'hidden' : 'block'} space-y-3 border-t border-[var(--theme-border)] pt-4 md:block`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <input
                    value={lane.name}
                    onChange={(event) => renameLane(lane.id, event.target.value)}
                    maxLength={120}
                    aria-label={`Lane ${lane.name} name`}
                    className="min-w-[10rem] flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm font-bold text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]"
                  />
                  <div className="flex gap-1">
                    <button
                      type="button"
                      onClick={() => moveLane(lane.id, -1)}
                      disabled={lane.order === 0}
                      aria-label={`Move lane ${lane.name} earlier`}
                      className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => moveLane(lane.id, 1)}
                      disabled={lane.order === orderedLanes.length - 1}
                      aria-label={`Move lane ${lane.name} later`}
                      className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      onClick={() => removeLane(lane.id)}
                      disabled={laneNodeCount(nodes, lane.id) > 0}
                      aria-label={`Remove lane ${lane.name}`}
                      title={laneNodeCount(nodes, lane.id) > 0 ? 'Move all steps out of this lane before removing it' : undefined}
                      className="min-h-9 rounded-lg px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-danger)] disabled:opacity-30"
                    >
                      Remove
                    </button>
                  </div>
                </div>
                {laneNodeCount(nodes, lane.id) > 0 ? (
                  <ol className="grid gap-2">
                    {laneNodes.map((node) => {
                      const index = laneNodes.findIndex((candidate) => candidate.id === node.id)
                      const otherLanes = orderedLanes.filter((candidate) => candidate.id !== lane.id)
                      return (
                        <li key={node.id} data-testid={`lane-item-${globalIndex.get(node.id)}`} className="flex items-center gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--theme-bg-panel)] font-black text-[var(--theme-text-muted)]">{index + 1}</span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate font-bold text-[var(--theme-text-primary)]">{node.label}</p>
                            <p className="text-xs uppercase tracking-wider text-[var(--theme-text-dim)]">{node.node_type}</p>
                            {(node.is_checkpoint || (node.convergence_gate && node.convergence_gate.length > 0)) && (
                              <div className="mt-1 flex flex-wrap gap-1">
                                {node.is_checkpoint && (
                                  <span className="inline-flex items-center rounded-full border border-[var(--theme-comic-accent)]/50 bg-[var(--theme-bg-panel)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-comic-accent)]">
                                    Checkpoint
                                  </span>
                                )}
                                {node.convergence_gate && node.convergence_gate.length > 0 && (
                                  <span className="inline-flex items-center rounded-full border border-[var(--theme-continuity-accent)]/50 bg-[var(--theme-bg-panel)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[var(--theme-continuity-accent)]">
                                    Convergence ({node.convergence_gate.length})
                                  </span>
                                )}
                              </div>
                            )}
                            {editingGateNodeId === node.id && (
                              <div className="mt-2 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3" data-testid={`convergence-editor-${node.id}`}>
                                <p className="mb-2 text-xs font-bold uppercase tracking-wider text-[var(--theme-text-muted)]">
                                  Wait for these steps before reading:
                                </p>
                                <div className="grid gap-1">
                                  {nodes
                                    .filter(
                                      (other) =>
                                        other.id !== node.id &&
                                        (other.node_type === 'issue' || other.node_type === 'crossover'),
                                    )
                                    .sort((a, b) => {
                                      const aLane = orderedLanes.find((l) => l.id === a.lane_id)
                                      const bLane = orderedLanes.find((l) => l.id === b.lane_id)
                                      return ((aLane?.order ?? 0) - (bLane?.order ?? 0)) || a.position - b.position
                                    })
                                    .map((other) => {
                                      const isSelected = (node.convergence_gate ?? []).some(
                                        (target) => target.node_id === other.id,
                                      )
                                      const otherLane = orderedLanes.find((l) => l.id === other.lane_id)
                                      return (
                                        <label
                                          key={other.id}
                                          className={`flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-sm ${isSelected ? 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)]' : 'text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-panel)]'}`}
                                        >
                                          <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={() => toggleConvergenceGate(node.id, other.id)}
                                            className="accent-[var(--theme-continuity-accent)]"
                                          />
                                          <span className="truncate">{other.label}</span>
                                          {otherLane && (
                                            <span className="ml-auto shrink-0 text-[10px] text-[var(--theme-text-dim)]">{otherLane.name}</span>
                                          )}
                                        </label>
                                      )
                                    })}
                                </div>
                                <button
                                  type="button"
                                  onClick={() => setEditingGateNodeId(null)}
                                  className="mt-2 min-h-9 rounded-lg border border-[var(--theme-border)] px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
                                >
                                  Done
                                </button>
                              </div>
                            )}
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {node.node_type === 'issue' && (
                              <button
                                type="button"
                                onClick={() => toggleCheckpoint(node.id)}
                                title={node.is_checkpoint ? 'Remove checkpoint' : 'Mark as checkpoint (blocks next step)'}
                                aria-label={node.is_checkpoint ? `Remove checkpoint from ${node.label}` : `Mark ${node.label} as checkpoint`}
                                className={`min-h-9 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-wider ${node.is_checkpoint ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-comic-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'}`}
                              >
                                {node.is_checkpoint ? '⚑' : '⚐'}
                              </button>
                            )}
                            {(node.node_type === 'issue' || node.node_type === 'crossover') && (
                              <button
                                type="button"
                                onClick={() => setEditingGateNodeId(editingGateNodeId === node.id ? null : node.id)}
                                title={editingGateNodeId === node.id ? 'Close convergence editor' : 'Edit convergence gate'}
                                aria-label={editingGateNodeId === node.id ? `Close convergence editor for ${node.label}` : `Edit convergence gate for ${node.label}`}
                                className={`min-h-9 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-wider ${(node.convergence_gate ?? []).length > 0 ? 'border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-continuity-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'}`}
                              >
                                ⇄
                              </button>
                            )}
                            {otherLanes.length > 0 && (
                              <select
                                aria-label={`Move ${node.label} to another lane`}
                                value={node.lane_id}
                                onChange={(event) => moveToLane(node.id, event.target.value)}
                                className="min-h-11 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 text-sm text-[var(--theme-text-primary)]"
                              >
                                <option value={node.lane_id}>In {lane.name}</option>
                                {otherLanes.map((target) => (
                                  <option key={target.id} value={target.id}>→ {target.name}</option>
                                ))}
                              </select>
                            )}
                            <button type="button" onClick={() => moveInLane(node.id, -1)} disabled={index === 0} aria-label={`Move ${node.label} earlier`} className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↑</button>
                            <button type="button" onClick={() => moveInLane(node.id, 1)} disabled={index === laneNodes.length - 1} aria-label={`Move ${node.label} later`} className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30">↓</button>
                            <button type="button" onClick={() => removeNode(node.id)} aria-label={`Remove ${node.label}`} className="min-h-11 rounded-lg px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-danger)]">Remove</button>
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                ) : (
                  <p className="rounded-xl border border-dashed border-[var(--theme-border)] p-4 text-center text-sm text-[var(--theme-text-dim)]">No steps in this lane yet.</p>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {saveError && <p role="alert" className="rounded-xl border border-[var(--theme-danger)] bg-[var(--theme-bg-panel)] p-3 text-[var(--theme-danger)]">{saveError}</p>}

      <div className="flex flex-col-reverse gap-3 border-t border-[var(--theme-border)] pt-5 sm:flex-row sm:items-center sm:justify-between">
        <button type="button" onClick={cancel} disabled={!isDirty || isSaving} className="min-h-11 rounded-xl border border-[var(--theme-border)] px-5 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)] disabled:opacity-40">Cancel changes</button>
        <div className="flex items-center gap-3 sm:ml-auto">
          {statusText && <p role="status" className={`text-xs font-bold ${isDirty ? 'text-[var(--theme-text-muted)]' : 'text-emerald-300'}`} aria-live="polite">{statusText}</p>}
          <button type="button" onClick={() => void save()} disabled={!isDirty || isSaving} className="min-h-11 min-w-[11rem] rounded-xl bg-[var(--theme-primary-action)] px-8 font-black text-stone-950 hover:bg-[var(--theme-primary-action-hover)] disabled:opacity-40 sm:flex-none">{isSaving ? 'Saving…' : 'Save plan'}</button>
        </div>
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
