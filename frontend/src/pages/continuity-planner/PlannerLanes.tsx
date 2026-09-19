import { laneNodeCount } from './plannerModel'
import type { ContinuityPlannerEditor } from './useContinuityPlannerEditor'

interface PlannerLanesProps {
  editor: ContinuityPlannerEditor
  planId: number | null
}

/**
 * Presentational reading-lanes section: lane headers, ordered node rows,
 * checkpoint/convergence controls, and lane management.
 * Holds no state; everything renders from the editor hook.
 */
export default function PlannerLanes({ editor, planId }: PlannerLanesProps) {
  const { orderedLanes, nodes } = editor

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
    <section aria-labelledby="lanes-heading" className="border-t border-[var(--theme-border)] pt-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2
            id="lanes-heading"
            className="text-sm font-black uppercase tracking-widest text-[var(--theme-text-primary)]"
          >
            Reading lanes
          </h2>
          <p className="text-xs text-[var(--theme-text-muted)]">
            {orderedLanes.length} {orderedLanes.length === 1 ? 'lane' : 'lanes'} · {nodes.length}{' '}
            {nodes.length === 1 ? 'step' : 'steps'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={editor.addLane}
            className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-transparent px-3 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
          >
            Add lane
          </button>
          {planId && (
            <button
              type="button"
              onClick={() => editor.setIsProjectionOpen(true)}
              className="min-h-11 rounded-xl border border-[var(--theme-border)] bg-transparent px-3 text-sm font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]"
            >
              Project to reading order
            </button>
          )}
        </div>
      </div>

      {orderedLanes.length > 1 && (
        <label className="mt-3 block text-xs font-bold uppercase tracking-widest text-[var(--theme-text-muted)] md:hidden">
          Viewing lane
          <select
            value={editor.targetLaneId}
            onChange={(event) => editor.setActiveLaneId(event.target.value)}
            className="mt-1 min-h-11 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 text-[var(--theme-text-primary)]"
          >
            {orderedLanes.map((lane) => (
              <option key={lane.id} value={lane.id}>
                {lane.name}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className="mt-4 space-y-6">
        {orderedLanes.map((lane) => {
          const laneNodes = nodes
            .filter((node) => node.lane_id === lane.id)
            .sort((a, b) => a.position - b.position)
          const isMobileHidden = orderedLanes.length > 1 && lane.id !== editor.targetLaneId
          return (
            <div
              key={lane.id}
              data-testid={`lane-${lane.id}`}
              className={`${isMobileHidden ? 'hidden' : 'block'} space-y-3 border-t border-[var(--theme-border)] pt-4 md:block`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <input
                  value={lane.name}
                  onChange={(event) => editor.renameLane(lane.id, event.target.value)}
                  maxLength={120}
                  aria-label={`Lane ${lane.name} name`}
                  className="min-w-[10rem] flex-1 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-3 py-2 text-sm font-bold text-[var(--theme-text-primary)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--theme-focus-ring)]"
                />
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => editor.moveLane(lane.id, -1)}
                    disabled={lane.order === 0}
                    aria-label={`Move lane ${lane.name} earlier`}
                    className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => editor.moveLane(lane.id, 1)}
                    disabled={lane.order === orderedLanes.length - 1}
                    aria-label={`Move lane ${lane.name} later`}
                    className="min-h-9 min-w-9 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => editor.removeLane(lane.id)}
                    disabled={laneNodeCount(nodes, lane.id) > 0}
                    aria-label={`Remove lane ${lane.name}`}
                    title={
                      laneNodeCount(nodes, lane.id) > 0
                        ? 'Move all steps out of this lane before removing it'
                        : undefined
                    }
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
                    const otherLanes = orderedLanes.filter(
                      (candidate) => candidate.id !== lane.id,
                    )
                    return (
                      <li
                        key={node.id}
                        data-testid={`lane-item-${globalIndex.get(node.id)}`}
                        className="flex items-center gap-3 rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[var(--theme-bg-panel)] font-black text-[var(--theme-text-muted)]">
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-bold text-[var(--theme-text-primary)]">
                            {node.label}
                          </p>
                          <p className="text-xs uppercase tracking-wider text-[var(--theme-text-dim)]">
                            {node.node_type}
                          </p>
                          {(node.is_checkpoint ||
                            (node.convergence_gate && node.convergence_gate.length > 0)) && (
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
                          {editor.editingGateNodeId === node.id && (
                            <div
                              className="mt-2 w-full rounded-xl border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] p-3"
                              data-testid={`convergence-editor-${node.id}`}
                            >
                              <p className="mb-2 text-xs font-bold uppercase tracking-wider text-[var(--theme-text-muted)]">
                                Wait for these steps before reading:
                              </p>
                              <div className="grid gap-1">
                                {nodes
                                  .filter(
                                    (other) =>
                                      other.id !== node.id &&
                                      (other.node_type === 'issue' ||
                                        other.node_type === 'crossover'),
                                  )
                                  .sort((a, b) => {
                                    const aLane = orderedLanes.find((l) => l.id === a.lane_id)
                                    const bLane = orderedLanes.find((l) => l.id === b.lane_id)
                                    return (
                                      (aLane?.order ?? 0) - (bLane?.order ?? 0) ||
                                      a.position - b.position
                                    )
                                  })
                                  .map((other) => {
                                    const isSelected = (node.convergence_gate ?? []).some(
                                      (target) => target.node_id === other.id,
                                    )
                                    const otherLane = orderedLanes.find(
                                      (l) => l.id === other.lane_id,
                                    )
                                    return (
                                      <label
                                        key={other.id}
                                        className={`flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1 text-sm ${isSelected ? 'bg-[var(--theme-bg-panel)] text-[var(--theme-text-primary)]' : 'text-[var(--theme-text-muted)] hover:bg-[var(--theme-bg-panel)]'}`}
                                      >
                                        <input
                                          type="checkbox"
                                          checked={isSelected}
                                          onChange={() =>
                                            editor.toggleConvergenceGate(node.id, other.id)
                                          }
                                          className="accent-[var(--theme-continuity-accent)]"
                                        />
                                        <span className="truncate">{other.label}</span>
                                        {otherLane && (
                                          <span className="ml-auto shrink-0 text-[10px] text-[var(--theme-text-dim)]">
                                            {otherLane.name}
                                          </span>
                                        )}
                                      </label>
                                    )
                                  })}
                              </div>
                              <button
                                type="button"
                                onClick={() => editor.setEditingGateNodeId(null)}
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
                              onClick={() => editor.toggleCheckpoint(node.id)}
                              title={
                                node.is_checkpoint
                                  ? 'Remove checkpoint'
                                  : 'Mark as checkpoint (blocks next step)'
                              }
                              aria-label={
                                node.is_checkpoint
                                  ? `Remove checkpoint from ${node.label}`
                                  : `Mark ${node.label} as checkpoint`
                              }
                              className={`min-h-9 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-wider ${node.is_checkpoint ? 'border-[var(--theme-comic-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-comic-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'}`}
                            >
                              {node.is_checkpoint ? '⚑' : '⚐'}
                            </button>
                          )}
                          {(node.node_type === 'issue' || node.node_type === 'crossover') && (
                            <button
                              type="button"
                              onClick={() =>
                                editor.setEditingGateNodeId(
                                  editor.editingGateNodeId === node.id ? null : node.id,
                                )
                              }
                              title={
                                editor.editingGateNodeId === node.id
                                  ? 'Close convergence editor'
                                  : 'Edit convergence gate'
                              }
                              aria-label={
                                editor.editingGateNodeId === node.id
                                  ? `Close convergence editor for ${node.label}`
                                  : `Edit convergence gate for ${node.label}`
                              }
                              className={`min-h-9 rounded-lg border px-2 text-[10px] font-bold uppercase tracking-wider ${(node.convergence_gate ?? []).length > 0 ? 'border-[var(--theme-continuity-accent)] bg-[var(--theme-bg-panel)] text-[var(--theme-continuity-accent)]' : 'border-[var(--theme-border)] text-[var(--theme-text-muted)] hover:text-[var(--theme-text-primary)]'}`}
                            >
                              ⇄
                            </button>
                          )}
                          {otherLanes.length > 0 && (
                            <select
                              aria-label={`Move ${node.label} to another lane`}
                              value={node.lane_id}
                              onChange={(event) => editor.moveToLane(node.id, event.target.value)}
                              className="min-h-11 rounded-lg border border-[var(--theme-border)] bg-[var(--theme-bg-panel)] px-2 text-sm text-[var(--theme-text-primary)]"
                            >
                              <option value={node.lane_id}>In {lane.name}</option>
                              {otherLanes.map((target) => (
                                <option key={target.id} value={target.id}>
                                  → {target.name}
                                </option>
                              ))}
                            </select>
                          )}
                          <button
                            type="button"
                            onClick={() => editor.moveInLane(node.id, -1)}
                            disabled={index === 0}
                            aria-label={`Move ${node.label} earlier`}
                            className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                          >
                            ↑
                          </button>
                          <button
                            type="button"
                            onClick={() => editor.moveInLane(node.id, 1)}
                            disabled={index === laneNodes.length - 1}
                            aria-label={`Move ${node.label} later`}
                            className="min-h-11 min-w-11 rounded-lg border border-[var(--theme-border)] text-[var(--theme-text-muted)] disabled:opacity-30"
                          >
                            ↓
                          </button>
                          <button
                            type="button"
                            onClick={() => editor.removeNode(node.id)}
                            aria-label={`Remove ${node.label}`}
                            className="min-h-11 rounded-lg px-3 text-xs font-bold text-[var(--theme-text-muted)] hover:text-[var(--theme-danger)]"
                          >
                            Remove
                          </button>
                        </div>
                      </li>
                    )
                  })}
                </ol>
              ) : (
                <p className="rounded-xl border border-dashed border-[var(--theme-border)] p-4 text-center text-sm text-[var(--theme-text-dim)]">
                  No steps in this lane yet.
                </p>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
