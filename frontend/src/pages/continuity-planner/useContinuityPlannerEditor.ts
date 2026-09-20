import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { DependencyGroup } from '../../services/api-dependency-groups'
import type {
  ContinuityPlan,
  ContinuityPlanNode,
  ContinuityPlanOrderingMode,
} from '../../services/api-continuity-plans'
import type { Issue, Thread } from '../../types'
import { isString } from '../../utils/runtimeChecks'
import { useSaveReadingPlan } from '../../hooks/useReadingPlans'
import {
  DEFAULT_LANE_ID,
  DEFAULT_LANE_NAME,
  DEFAULT_PLAN_NAME,
  LAST_PLAN_KEY,
  buildPayload,
  getConflictMessage,
  laneNodeCount,
  normalizePositions,
  type PlannerLane,
  type PlannerNode,
} from './plannerModel'

export interface ContinuityPlannerEditorInputs {
  planId: number | null
  planData: ContinuityPlan | undefined
  planPending: boolean
  groups: DependencyGroup[]
  groupsPending: boolean
  threadsPending: boolean
  isInvalidRoute: boolean
  addFromCblRequested: boolean
}

/**
 * Owns Continuity Planner editor draft state and orchestration.
 *
 * Server collections stay in React Query hooks owned by the page; this hook
 * hydrates local draft state from them and exposes editor actions plus the
 * derived values presentational components need. It holds no markup.
 */
export function useContinuityPlannerEditor({
  planId,
  planData,
  planPending,
  groups,
  groupsPending,
  threadsPending,
  isInvalidRoute,
  addFromCblRequested,
}: ContinuityPlannerEditorInputs) {
  const navigate = useNavigate()
  const savePlan = useSaveReadingPlan(planId)

  const [selectedThreadId, setSelectedThreadId] = useState<number | null>(null)
  const [name, setName] = useState(DEFAULT_PLAN_NAME)
  const [orderingMode, setOrderingMode] = useState<ContinuityPlanOrderingMode>('informational')
  const [lanes, setLanes] = useState<PlannerLane[]>([
    { id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 },
  ])
  const [nodes, setNodes] = useState<PlannerNode[]>([])
  const [activeLaneId, setActiveLaneId] = useState(DEFAULT_LANE_ID)
  const [savedName, setSavedName] = useState('')
  const [savedLanes, setSavedLanes] = useState<PlannerLane[]>([])
  const [savedNodes, setSavedNodes] = useState<PlannerNode[]>([])
  const [savedOrderingMode, setSavedOrderingMode] =
    useState<ContinuityPlanOrderingMode>('informational')
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [selectedIssue, setSelectedIssue] = useState<Issue | null>(null)
  const [selectedGroupId, setSelectedGroupId] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [cblCommitPending, setCblCommitPending] = useState(false)
  const [isProjectionOpen, setIsProjectionOpen] = useState(false)
  const [laneSeq, setLaneSeq] = useState(0)
  const [editingGateNodeId, setEditingGateNodeId] = useState<string | null>(null)
  const lastPlanId =
    typeof window === 'undefined' ? null : window.localStorage.getItem(LAST_PLAN_KEY)

  const hydrateLabels = useCallback(
    (rawNodes: ContinuityPlanNode[], loadedGroups: DependencyGroup[]): PlannerNode[] => {
      const groupNames = new Map(loadedGroups.map((group) => [group.id, group.name]))
      return rawNodes.map((node): PlannerNode => {
        // SAFETY: rawNodes are ContinuityPlanNode and PlannerNode only adds optional display fields set below.
        const plannerNode = node as PlannerNode
        const stored = isString(plannerNode.label) ? plannerNode.label.trim() : ''
        if (node.node_type === 'crossover') {
          if (stored) return { ...plannerNode, label: stored }
          return { ...plannerNode, label: groupNames.get(node.ref_id) ?? '[deleted crossover]' }
        }
        if (node.node_type === 'thread') {
          if (stored) return { ...plannerNode, label: stored }
          return { ...plannerNode, label: '[deleted series]' }
        }
        if (stored) return { ...plannerNode, label: stored }
        return { ...plannerNode, label: '[deleted series]' }
      })
    },
    [],
  )

  // Hydrate editor state from plan data when it arrives
  const planLoaded = planData != null && !planPending
  const groupsLoaded = !groupsPending
  const [planHydrated, setPlanHydrated] = useState(false)

  useEffect(() => {
    setPlanHydrated(false)
  }, [planId])

  useEffect(() => {
    if (isInvalidRoute) {
      return
    }
    if (planId == null && !planHydrated && !threadsPending && groupsLoaded) {
      setSavedName(DEFAULT_PLAN_NAME)
      setSavedLanes([{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }])
      setSavedNodes([])
      setSavedOrderingMode('informational')
      setPlanHydrated(true)
      return
    }
    if (planLoaded && groupsLoaded && !planHydrated && planData) {
      const loadedLanes = (
        planData.lanes.length > 0
          ? planData.lanes
          : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
      )
        .map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
        .sort((a, b) => a.order - b.order)
      const hydrated = hydrateLabels(
        [...planData.nodes].sort((a, b) => a.position - b.position),
        groups,
      )
      setName(planData.name)
      setLanes(loadedLanes)
      setNodes(normalizePositions(hydrated))
      setOrderingMode(planData.ordering_mode)
      setSavedName(planData.name)
      setSavedLanes(loadedLanes)
      setSavedNodes(normalizePositions(hydrated))
      setSavedOrderingMode(planData.ordering_mode)
      setActiveLaneId(loadedLanes[0]?.id ?? DEFAULT_LANE_ID)
      window.localStorage.setItem(LAST_PLAN_KEY, String(planData.id))
      setPlanHydrated(true)
    }
  }, [
    planLoaded,
    groupsLoaded,
    planHydrated,
    planData,
    planId,
    isInvalidRoute,
    threadsPending,
    groups,
    hydrateLabels,
  ])

  const isDirty =
    name !== savedName ||
    orderingMode !== savedOrderingMode ||
    JSON.stringify(lanes) !== JSON.stringify(savedLanes) ||
    JSON.stringify(nodes) !== JSON.stringify(savedNodes)

  const orderedLanes = [...lanes].sort((a, b) => a.order - b.order)
  const targetLaneId = orderedLanes.some((lane) => lane.id === activeLaneId)
    ? activeLaneId
    : (orderedLanes[0]?.id ?? DEFAULT_LANE_ID)

  const selectThread = (thread: Thread | null) => {
    setSelectedThread(thread)
    setSelectedIssue(null)
    setSelectedThreadId(thread?.id ?? null)
  }

  const addNode = (node: Omit<PlannerNode, 'lane_id' | 'position' | 'label'>, label: string) => {
    const laneId = targetLaneId
    const nextPosition = laneNodeCount(nodes, laneId)
    setNodes((current) =>
      normalizePositions([...current, { ...node, lane_id: laneId, position: nextPosition, label }]),
    )
  }

  const addIssue = () => {
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
      return normalizePositions(
        current.map((candidate) => (candidate.id === nodeId ? moved : candidate)),
      )
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
    setNodes((current) => {
      const targetNode = current.find((n) => n.id === targetNodeId)
      if (!targetNode) return current
      return current.map((node) => {
        if (node.id !== nodeId) return node
        const gate = node.convergence_gate ?? []
        const exists = gate.some((target) => target.node_id === targetNodeId)
        const updated = exists
          ? gate.filter((target) => target.node_id !== targetNodeId)
          : [...gate, { node_type: targetNode.node_type, node_id: targetNodeId }]
        return { ...node, convergence_gate: updated }
      })
    })
  }

  const addLane = () => {
    if (lanes.length >= 1 && orderingMode === 'strict_sequential') {
      setOrderingMode('informational')
    }
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
    setActiveLaneId(
      (current) =>
        current === laneId ? (lanes.find((lane) => lane.id !== laneId)?.id ?? '') : current,
    )
  }

  const save = async () => {
    if (!name.trim()) {
      setSaveError('Enter a plan name.')
      return
    }
    setSaveError(null)
    try {
      const payload = buildPayload(name, lanes, nodes, orderingMode)
      const saved = await savePlan.mutateAsync(payload)
      const nextSavedLanes = (
        saved.lanes.length > 0
          ? saved.lanes
          : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
      )
        .map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
        .sort((a, b) => a.order - b.order)
      const normalized = normalizePositions(nodes)
      setName(saved.name)
      setLanes(nextSavedLanes)
      setNodes(normalized)
      setOrderingMode(saved.ordering_mode)
      setSavedName(saved.name)
      setSavedLanes(nextSavedLanes)
      setSavedNodes(normalized)
      setSavedOrderingMode(saved.ordering_mode)
      window.localStorage.setItem(LAST_PLAN_KEY, String(saved.id))
      if (!planId) {
        navigate(`/continuity-plans/${saved.id}${addFromCblRequested ? '?addFrom=cbl' : ''}`, {
          replace: true,
        })
      }
    } catch (error) {
      setSaveError(getConflictMessage(error, nodes))
    }
  }

  const acceptCommittedPlan = (committed: ContinuityPlan) => {
    const committedLanes = (
      committed.lanes.length > 0
        ? committed.lanes
        : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }]
    )
      .map((lane) => ({ id: lane.id, name: lane.name, order: lane.order }))
      .sort((a, b) => a.order - b.order)
    const committedNodes = normalizePositions(
      hydrateLabels([...committed.nodes].sort((a, b) => a.position - b.position), groups),
    )
    setName(committed.name)
    setLanes(committedLanes)
    setNodes(committedNodes)
    setOrderingMode(committed.ordering_mode)
    setSavedName(committed.name)
    setSavedLanes(committedLanes)
    setSavedNodes(committedNodes)
    setSavedOrderingMode(committed.ordering_mode)
    setActiveLaneId(committedLanes[0]?.id ?? DEFAULT_LANE_ID)
    setSaveError(null)
  }

  const cancel = () => {
    setName(savedName || DEFAULT_PLAN_NAME)
    setLanes(
      savedLanes.length > 0
        ? savedLanes
        : [{ id: DEFAULT_LANE_ID, name: DEFAULT_LANE_NAME, order: 0 }],
    )
    setNodes(savedNodes)
    setOrderingMode(savedOrderingMode || 'informational')
    setActiveLaneId(savedLanes[0]?.id ?? DEFAULT_LANE_ID)
    setSaveError(null)
  }

  const isSaving = savePlan.isPending || cblCommitPending
  const statusText = isSaving
    ? 'Saving…'
    : saveError
      ? null
      : isDirty
        ? 'Unsaved changes'
        : planId
          ? 'Saved'
          : 'New plan'

  const sourcePaths = Array.from(
    new Set(
      nodes.flatMap((node) => [
        ...(node.source_paths ?? []),
        ...(node.source_cbl_placements ?? []).map((placement) => placement.source_path),
      ]),
    ),
  )

  return {
    // draft state
    name,
    orderingMode,
    lanes,
    orderedLanes,
    nodes,
    activeLaneId,
    targetLaneId,
    selectedThread,
    selectedThreadId,
    selectedIssue,
    selectedGroupId,
    saveError,
    cblCommitPending,
    isProjectionOpen,
    editingGateNodeId,
    lastPlanId,
    savedName,
    isDirty,
    isSaving,
    statusText,
    sourcePaths,
    saveMutationPending: savePlan.isPending,
    // setters for controlled presentational inputs
    setName,
    setOrderingMode,
    setActiveLaneId,
    setSelectedIssue,
    setSelectedGroupId,
    setCblCommitPending,
    setIsProjectionOpen,
    setEditingGateNodeId,
    // orchestration actions
    selectThread,
    addIssue,
    addCrossover,
    moveInLane,
    moveToLane,
    removeNode,
    toggleCheckpoint,
    toggleConvergenceGate,
    addLane,
    renameLane,
    moveLane,
    removeLane,
    save,
    cancel,
    acceptCommittedPlan,
  }
}

export type ContinuityPlannerEditor = ReturnType<typeof useContinuityPlannerEditor>
