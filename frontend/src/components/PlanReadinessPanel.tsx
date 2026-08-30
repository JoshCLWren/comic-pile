import { useMemo } from 'react'
import { usePlanReadiness } from '../hooks/usePlanReadiness'
import type { ContinuityPlanNodeReadiness } from '../services/api-continuity-plans'

interface PlanReadinessPanelProps {
  planId: number | null
  refreshKey?: number
}

type NodeState = 'readable' | 'blocked' | 'complete' | 'unavailable'

const STATE_LABEL: Readonly<Record<NodeState, string>> = {
  readable: 'Readable',
  blocked: 'Blocked',
  complete: 'Complete',
  unavailable: 'Unavailable',
}

const STATE_BADGE_CLASS: Readonly<Record<NodeState, string>> = {
  readable: 'border-emerald-700/50 bg-emerald-950/30 text-emerald-300',
  blocked: 'border-rose-800/50 bg-rose-950/30 text-rose-300',
  complete: 'border-stone-600/60 bg-stone-800/60 text-stone-300',
  unavailable: 'border-amber-700/50 bg-amber-950/25 text-amber-300',
}

function nodeState(node: ContinuityPlanNodeReadiness): NodeState {
  if (
    node.diagnostics.some(
      (diagnostic) =>
        diagnostic.code === 'dangling_plan_reference' ||
        diagnostic.code === 'plan_cycle_detected',
    )
  ) {
    return 'unavailable'
  }
  if (node.is_complete) return 'complete'
  if (!node.is_readable) return 'blocked'
  return 'readable'
}

function blockerReason(node: ContinuityPlanNodeReadiness): string | null {
  const dangling = node.diagnostics.find((d) => d.code === 'dangling_plan_reference')
  if (dangling) return 'This step no longer exists in your library.'
  const cycle = node.diagnostics.find((d) => d.code === 'plan_cycle_detected')
  if (cycle) return 'This step sits on a continuity cycle and can never become readable.'
  if (node.is_complete) return 'Every issue in this step has been read.'
  if (node.is_readable) return 'Ready to read now.'
  const blocker = node.blockers[0]
  if (!blocker) return 'The server reported this step as blocked without prerequisite details.'
  if (blocker.satisfaction_type === 'checkpoint') return 'Waiting on checkpoint to be read.'
  if (blocker.satisfaction_type === 'converged') return 'Waiting on convergence gate prerequisites.'
  if (blocker.unread_issue_details && blocker.unread_issue_details.length > 0) {
    return `Waiting on ${blocker.unread_issue_details.map((detail) => detail.label).join(', ')}.`
  }
  return `Waiting on ${blocker.source_label}.`
}

export default function PlanReadinessPanel({ planId, refreshKey = 0 }: PlanReadinessPanelProps) {
  const { readiness, isLoading, error, refetch } = usePlanReadiness(planId, refreshKey)

  const grouped = useMemo(() => {
    if (!readiness) return []
    const groups: Array<{ laneId: string; laneName: string; nodes: ContinuityPlanNodeReadiness[] }> =
      []
    const index = new Map<string, number>()
    for (const lane of [...readiness.lanes].sort((a, b) => a.order - b.order)) {
      index.set(lane.id, groups.length)
      groups.push({ laneId: lane.id, laneName: lane.name, nodes: [] })
    }
    for (const node of readiness.nodes) {
      const groupIndex = index.get(node.lane_id)
      if (groupIndex === undefined) continue
      groups[groupIndex].nodes.push(node)
    }
    for (const node of readiness.nodes) {
      if (!index.has(node.lane_id)) {
        let fallback = groups.find((group) => group.laneId === '__unlane__')
        if (!fallback) {
          fallback = { laneId: '__unlane__', laneName: 'Other steps', nodes: [] }
          groups.push(fallback)
        }
        fallback.nodes.push(node)
      }
    }
    return groups.filter((group) => group.nodes.length > 0)
  }, [readiness])

  if (planId == null) return null

  if (isLoading && !readiness) {
    return (
      <section
        aria-labelledby="plan-readiness-heading"
        data-testid="plan-readiness-loading"
        role="status"
        className="rounded-2xl border border-white/10 bg-white/[0.04] p-4"
      >
        <h2 id="plan-readiness-heading" className="text-xs font-black uppercase tracking-widest text-stone-400">
          Live readiness
        </h2>
        <p className="mt-2 text-sm text-stone-400">Checking plan readiness…</p>
      </section>
    )
  }

  if (error || !readiness) {
    return (
      <section
        aria-labelledby="plan-readiness-heading"
        data-testid="plan-readiness-error"
        className="rounded-2xl border border-rose-800/40 bg-rose-950/20 p-4"
        role="alert"
      >
        <h2 id="plan-readiness-heading" className="text-xs font-black uppercase tracking-widest text-rose-300">
          Live readiness
        </h2>
        <p className="mt-2 text-sm text-rose-200">
          Readiness could not be verified. Your saved plan is unchanged.
        </p>
        <button
          type="button"
          onClick={() => refetch()}
          data-testid="plan-readiness-retry"
          className="mt-3 min-h-11 rounded-xl border border-rose-700/40 px-4 font-bold text-rose-200 hover:bg-rose-900/30"
        >
          Retry readiness
        </button>
      </section>
    )
  }

  if (readiness.nodes.length === 0) {
    return (
      <section
        aria-labelledby="plan-readiness-heading"
        data-testid="plan-readiness-empty"
        className="rounded-2xl border border-white/10 bg-white/[0.04] p-4"
      >
        <h2 id="plan-readiness-heading" className="text-xs font-black uppercase tracking-widest text-stone-400">
          Live readiness
        </h2>
        <p className="mt-2 text-sm text-stone-400">
          Add reading steps and save to see live readiness here.
        </p>
      </section>
    )
  }

  const summary = readiness.summary

  return (
    <section
      aria-labelledby="plan-readiness-heading"
      data-testid="plan-readiness-panel"
      className="rounded-2xl border border-white/10 bg-white/[0.04] p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="plan-readiness-heading" className="text-xs font-black uppercase tracking-widest text-stone-400">
          Live readiness
        </h2>
        <p
          data-testid="plan-readiness-summary"
          aria-label={`Readiness summary: ${summary.readable} readable, ${summary.blocked} blocked, ${summary.complete} complete`}
          className="text-xs font-bold text-stone-300"
        >
          {summary.readable} readable · {summary.blocked} blocked · {summary.complete} complete
          {summary.unavailable > 0 ? ` · ${summary.unavailable} unavailable` : ''}
        </p>
      </div>

      <div className="mt-3 grid gap-3">
        {grouped.map((group) => (
          <div key={group.laneId} data-testid={`plan-readiness-lane-${group.laneId}`}>
            <p className="text-[10px] font-black uppercase tracking-wider text-stone-500">
              {group.laneName}
            </p>
            <ul className="mt-1 grid gap-1.5" aria-label={`Live readiness for ${group.laneName}`}>
              {group.nodes.map((node) => {
                const state = nodeState(node)
                return (
                  <li
                    key={node.node_id}
                    data-testid={`plan-node-readiness-${node.node_id}`}
                    data-state={state}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-white/10 bg-black/20 p-2.5"
                  >
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[10px] font-black uppercase tracking-wider ${STATE_BADGE_CLASS[state]}`}
                    >
                      {STATE_LABEL[state]}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm font-bold text-stone-100">
                      {node.label}
                    </span>
                    {node.blockers.some((b) => b.satisfaction_type === 'checkpoint') && (
                      <span className="inline-flex shrink-0 items-center rounded-full border border-amber-600/50 bg-amber-950/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300">
                        Checkpoint
                      </span>
                    )}
                    {node.blockers.some((b) => b.satisfaction_type === 'converged') && (
                      <span className="inline-flex shrink-0 items-center rounded-full border border-violet-600/50 bg-violet-950/40 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-violet-300">
                        Convergence
                      </span>
                    )}
                    <span className="w-full text-[11px] leading-relaxed text-stone-400 sm:w-auto">
                      {blockerReason(node)}
                    </span>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>

      {readiness.plan_diagnostics.length > 0 && (
        <p role="status" data-testid="plan-readiness-diagnostics" className="mt-3 text-[11px] text-amber-300">
          Some saved references could not be evaluated and are shown as unavailable.
        </p>
      )}
    </section>
  )
}
