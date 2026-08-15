import { useMemo } from 'react'
import Modal from '../../../components/Modal'
import { useContinuityChains } from '../../../hooks/useContinuityChains'
import { useContinuityReadiness } from '../../../hooks/useContinuityReadiness'
import type { ReadingOrder } from '../../../services/api-reading-orders'
import type {
  ContinuityBlocker,
  ContinuityChainDiagnostic,
  ContinuityChainNode,
  ContinuityChainResponse,
} from '../../../services/api-continuity-readiness'
import type { ConnectedThreadInfo } from '../../../types'

interface ReadingRouteExplanationProps {
  isOpen: boolean
  issueId: number | null | undefined
  issueLabel: string
  readingOrders: ReadingOrder[]
  connectedThreads: ConnectedThreadInfo[]
  onClose: () => void
}

const DIAGNOSTIC_CODE_LABEL: Readonly<Record<ContinuityChainDiagnostic['code'], string>> = {
  cycle_detected: 'cyclic continuity state',
  depth_limit_exceeded: 'chain depth exceeded while traversing',
  node_limit_exceeded: 'chain breadth exceeded while traversing',
}

function partitionDirectBlockers(chains: ContinuityChainResponse | null) {
  const directBlockers: ContinuityBlocker[] = []
  if (chains && chains.direct_blockers.length > 0) {
    directBlockers.push(...chains.direct_blockers)
  }
  return directBlockers
}

function describeNode(node: ContinuityChainNode): string {
  return `${node.label}${node.is_readable ? '' : ' (unread)'}`
}

function describeBranchConvergence(
  leaves: ContinuityChainNode[],
  parallelBranches: ContinuityChainNode[][][],
): string {
  const leafSets = parallelBranches.map((branch) =>
    branch.flatMap((path) => (path.length > 0 ? [path[path.length - 1]] : [])),
  )
  const sharedLeaves = leaves.filter((leaf) =>
    leafSets.every((set) =>
      set.some(
        (candidate) =>
          candidate.node_id === leaf.node_id &&
          candidate.node_type === leaf.node_type,
      ),
    ),
  )
  return sharedLeaves.length > 0 ? 'Converging branches' : ''
}

export function ReadingRouteExplanation({
  isOpen,
  issueId,
  issueLabel,
  readingOrders,
  connectedThreads,
  onClose,
}: ReadingRouteExplanationProps) {
  const readinessState = useContinuityReadiness(isOpen ? issueId : null)
  const chainsState = useContinuityChains(isOpen ? issueId : null)
  const readability = readinessState.readiness?.is_readable ?? null

  const sortedReadingOrders = useMemo(
    () => [...readingOrders].sort((a, b) => a.name.localeCompare(b.name)),
    [readingOrders],
  )

  const upstreamThreads = useMemo(
    () =>
      connectedThreads.filter(
        (thread) =>
          thread.connection_type === 'blocked_by' ||
          thread.connection_type === 'blocks & blocked_by',
      ),
    [connectedThreads],
  )

  const downstreamUnlocks = useMemo(
    () =>
      connectedThreads.filter(
        (thread) =>
          thread.connection_type === 'blocks' ||
          thread.connection_type === 'blocks & blocked_by',
      ),
    [connectedThreads],
  )

  const readablePrerequisites = useMemo(
    () => chainsState.chains?.readable_prerequisites ?? [],
    [chainsState.chains],
  )
  const chains = useMemo(() => chainsState.chains ?? null, [chainsState.chains])
  const directBlockers = useMemo(
    () => partitionDirectBlockers(chains),
    [chains],
  )
  const transitiveChains = useMemo(
    () => (chains ? chains.chains : []),
    [chains],
  )
  const diagnostics = useMemo(
    () => (chains ? chains.diagnostics : []),
    [chains],
  )

  const hasBridgeState = issueId != null ? (readinessState.isLoading || chainsState.isLoading) : false

  const headingForEligibility =
    readability === true
      ? 'Currently readable'
      : readability === false
        ? 'Blocked by continuity'
        : 'Readiness may be unavailable'

  return (
    <Modal
      isOpen={isOpen}
      title={issueLabel}
      onClose={onClose}
      autoFocus={false}
      data-testid="reading-route-explanation"
      overlayClassName="bg-black/70 backdrop-blur-sm"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.18em] text-amber-500">
        Why this issue is next
      </p>

      <section
        aria-labelledby="eligibility-heading"
        className="rounded-2xl border border-white/10 bg-white/[0.04] p-3"
      >
        <h3 id="eligibility-heading" className="text-xs font-black text-stone-200">
          Continuity eligibility
        </h3>
        {issueId == null ? (
          <p className="mt-2 text-[11px] text-amber-200">
            The exact issue identity is unavailable, so eligibility cannot be verified.
          </p>
        ) : hasBridgeState ? (
          <p
            className="mt-2 text-[11px] text-stone-400"
            role="status"
            aria-busy
            data-testid="chains-loading"
          >
            Checking authoritative readiness…
          </p>
        ) : readinessState.error || !readinessState.readiness ? (
          <div className="mt-2">
            <p className="text-[11px] text-rose-200" role="alert">
              Readiness is unavailable. The pending roll has not been changed.
            </p>
            <button
              type="button"
              onClick={() => {
                readinessState.refetch()
                chainsState.refetch()
              }}
              className="mt-3 min-h-11 rounded-xl border border-rose-700/40 px-4 text-xs font-black text-rose-200"
            >
              Retry readiness
            </button>
          </div>
        ) : chainsState.error ? (
          <div className="mt-2">
            <p
              className={`text-[11px] font-bold ${readability ? 'text-emerald-300' : 'text-rose-300'}`}
            >
              {headingForEligibility}
            </p>
            <p className="mt-1 text-[11px] text-rose-200" role="alert">
              The authoritative readiness result is shown above, but the expanded prerequisite
              detail could not be loaded.
            </p>
            <button
              type="button"
              onClick={chainsState.refetch}
              className="mt-3 min-h-11 rounded-xl border border-rose-700/40 px-4 text-xs font-black text-rose-200"
            >
              Retry continuity detail
            </button>
          </div>
        ) : readability ? (
          <div className="mt-2">
            <p className="text-[11px] font-bold text-emerald-300">{headingForEligibility}</p>
            <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
              All known direct prerequisites are satisfied. No unresolved hard prerequisite was returned for this issue.
            </p>
          </div>
        ) : (
          <div className="mt-2">
            <p className="text-[11px] font-bold text-rose-300">{headingForEligibility}</p>
          </div>
        )}
      </section>

      {issueId != null ? (
        <>
          {!(readinessState.error || chainsState.error) ? (
            <>
          {directBlockers.length > 0 ? (
            <section
              aria-labelledby="direct-blockers-heading"
              className="rounded-2xl border border-rose-900/30 bg-rose-950/20 p-3"
            >
              <h3
                id="direct-blockers-heading"
                className="text-xs font-black text-rose-300"
              >
                Unresolved direct blockers
              </h3>
              <p className="mt-1 text-[11px] text-rose-200">
                These hard prerequisites must be satisfied before this issue is next.
              </p>
              <ul
                aria-label="Unresolved direct blockers"
                className="mt-2 grid gap-2"
              >
                {directBlockers.map((blocker) => (
                  <li
                    key={`${blocker.rule_id}-${blocker.source_type}-${blocker.source_id}`}
                    className="rounded-xl border border-rose-800/40 bg-rose-900/20 p-3"
                  >
                    <span className="text-[10px] font-black uppercase tracking-wider text-rose-400">
                      Unresolved direct blocker
                    </span>
                    <p className="mt-1 text-sm font-bold text-stone-200">
                      {blocker.source_label}
                    </p>
                    {blocker.note ? (
                      <p className="mt-1 text-[11px] text-stone-400">{blocker.note}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {readablePrerequisites.length > 0 ? (
            <section
              aria-labelledby="readable-prerequisites-heading"
              className="rounded-2xl border border-amber-800/30 bg-amber-950/20 p-3"
            >
              <h3
                id="readable-prerequisites-heading"
                className="text-xs font-black text-amber-300"
              >
                Currently readable prerequisites
              </h3>
              <p className="mt-1 text-[11px] text-amber-200">
                These hard prerequisites are read; the bounded transitive chain identifies them as the next leaves to return once blockers clear.
              </p>
              <ul
                aria-label="Currently readable prerequisites"
                className="mt-2 grid gap-2"
              >
                {readablePrerequisites.map((node) => (
                  <li
                    key={`${node.node_type}-${node.node_id}`}
                    className="rounded-xl border border-amber-700/30 bg-amber-900/20 p-3"
                    data-testid={`readable-prerequisite-${node.node_id}`}
                  >
                    <span className="text-[10px] font-black uppercase tracking-wider text-amber-400">
                      Currently readable issue
                    </span>
                    <p className="mt-1 text-sm font-bold text-stone-200">{node.label}</p>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {transitiveChains.length > 0 ? (
            <section
              aria-labelledby="transitive-chains-heading"
              className="rounded-2xl border border-white/10 bg-white/[0.04] p-3"
            >
              <h3
                id="transitive-chains-heading"
                className="text-xs font-black text-stone-200"
              >
                Bounded prerequisite chain
              </h3>
              <p className="mt-1 text-[11px] text-stone-400">
                Parallel lanes remain visually parallel. Connecting lines may clarify convergence, but the information stays clear without relying on geometry or color.
              </p>
              <ul
                aria-label="Parallel prerequisite lanes"
                className="mt-2 grid gap-3"
                data-testid="parallel-prerequisite-lanes"
              >
                {transitiveChains.map((path, laneIndex) => (
                  <li
                    key={`lane-${laneIndex}`}
                    className="rounded-xl border border-white/10 bg-black/20 p-3"
                    data-testid={`prerequisite-lane-${laneIndex}`}
                    aria-label={`Parallel lane ${laneIndex + 1}`}
                  >
                    <span className="text-[10px] font-black uppercase tracking-wider text-stone-500">
                      Parallel lane {laneIndex + 1}
                    </span>
                    <ol className="mt-2 grid gap-1.5">
                      {path.map((node, nodeIndex) => (
                        <li
                          key={`${laneIndex}-${nodeIndex}-${node.node_type}-${node.node_id}`}
                          className="flex items-baseline gap-2 text-[11px] leading-relaxed"
                        >
                          <span aria-hidden="true" className="text-stone-500">
                            {nodeIndex > 0 ? '↳' : '·'}
                          </span>
                          <span className="font-bold text-stone-100">
                            {describeNode(node)}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </li>
                ))}
              </ul>
              {transitiveChains.length > 1 ? (
                <p className="mt-2 text-[11px] font-bold text-stone-400">
                  {describeBranchConvergence(
                    readablePrerequisites,
                    transitiveChains.map((path) => [path]),
                  )}
                </p>
              ) : null}
            </section>
          ) : null}

          {diagnostics.length > 0 ? (
            <section
              aria-labelledby="diagnostics-heading"
              className="rounded-2xl border border-amber-700/40 bg-amber-950/15 p-3"
              role="alert"
            >
              <h3 id="diagnostics-heading" className="text-xs font-black text-amber-300">
                Continuity diagnostic
              </h3>
              <p className="mt-1 text-[11px] text-amber-200">
                Some continuity state could not be traversed safely. The direct readiness and unmatched prerequisite detail stay authoritative.
              </p>
              <ul
                aria-label="Continuity diagnostics"
                className="mt-2 grid gap-2"
                data-testid="continuity-diagnostics"
              >
                {diagnostics.map((diagnostic) => (
                  <li
                    key={`${diagnostic.code}-${diagnostic.node_type}-${diagnostic.node_id}`}
                    data-testid={`continuity-diagnostic-${diagnostic.code}`}
                    className="rounded-xl border border-amber-700/40 bg-amber-900/15 p-2"
                  >
                    <p className="text-[11px] font-bold text-amber-200">
                      {DIAGNOSTIC_CODE_LABEL[diagnostic.code] ?? diagnostic.code}
                    </p>
                    <p className="mt-1 text-[10px] text-stone-400">
                      {diagnostic.node_type} {diagnostic.node_id}
                      {diagnostic.limit != null ? ` · limit ${diagnostic.limit}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
            ) : null}
            </>
          ) : null}

            {upstreamThreads.length > 0 ? (
              <section
                aria-labelledby="upstream-locks-heading"
              className="rounded-2xl border border-blue-900/30 bg-blue-950/15 p-3"
            >
              <h3
                id="upstream-locks-heading"
                className="text-xs font-black text-blue-300"
              >
                Hard prerequisite threads
              </h3>
              <p className="mt-1 text-[11px] text-stone-400">
                Connected threads whose dependencies block this issue.
              </p>
              <ul
                aria-label="Hard prerequisite threads"
                className="mt-2 flex flex-wrap gap-2"
              >
                {upstreamThreads.map((thread) => (
                  <li
                    key={`${thread.thread_id}-${thread.dependency_id}`}
                    className="rounded-full border border-blue-700/40 px-3 py-1 text-[11px] font-bold text-blue-200"
                  >
                    {thread.title}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {downstreamUnlocks.length > 0 ? (
            <section
              aria-labelledby="downstream-unlocks-heading"
              className="rounded-2xl border border-emerald-800/30 bg-emerald-950/15 p-3"
            >
              <h3
                id="downstream-unlocks-heading"
                className="text-xs font-black text-emerald-300"
              >
                Verified downstream unlocks
              </h3>
              <p className="mt-1 text-[11px] text-stone-400">
                Threads whose continuity eligibility improves by completing this issue.
              </p>
              <ul
                aria-label="Verified downstream unlocks"
                className="mt-2 flex flex-wrap gap-2"
              >
                {downstreamUnlocks.map((thread) => (
                  <li
                    key={`${thread.thread_id}-${thread.dependency_id}`}
                    className="rounded-full border border-emerald-700/40 px-3 py-1 text-[11px] font-bold text-emerald-200"
                  >
                    {thread.title}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          {sortedReadingOrders.length > 0 ? (
            <section aria-labelledby="named-routes-heading">
              <h3
                id="named-routes-heading"
                className="text-xs font-black text-stone-200"
              >
                Named reading routes
              </h3>
              <p className="mt-1 text-[11px] text-stone-500">
                Membership is informational and does not imply a hard dependency.
              </p>
              <ul className="mt-2 grid gap-2 md:grid-cols-2">
                {sortedReadingOrders.map((order) => {
                  const progress =
                    order.total_items > 0
                      ? Math.round((order.completed_items / order.total_items) * 100)
                      : 0
                  return (
                    <li
                      key={order.id}
                      className="rounded-xl border border-blue-800/30 bg-blue-950/15 p-3"
                    >
                      <p className="text-sm font-black text-blue-100">{order.name}</p>
                      <p className="mt-1 text-[11px] text-stone-400">
                        {order.completed_items} of {order.total_items} complete · {progress}%
                      </p>
                    </li>
                  )
                })}
              </ul>
            </section>
          ) : (
            readability === true && upstreamThreads.length === 0 ? (
              <section
                aria-labelledby="routes-heading"
                className="rounded-2xl border border-white/10 bg-white/[0.04] p-3"
              >
                <h3
                  id="routes-heading"
                  className="text-xs font-black text-stone-200"
                >
                  No named reading routes
                </h3>
                <p className="mt-1 text-[11px] text-amber-200">
                  This eligible issue is not part of any informational named route or crossover.
                </p>
              </section>
            ) : null
          )}

          {!hasBridgeState &&
          !chainsState.error &&
          transitiveChains.length === 0 &&
          directBlockers.length === 0 &&
          readablePrerequisites.length === 0 &&
          diagnostics.length === 0 &&
          upstreamThreads.length === 0 &&
          sortedReadingOrders.length === 0 ? (
            <section
              aria-labelledby="no-routes-heading"
              className="rounded-2xl border border-white/10 bg-white/[0.04] p-3"
              data-testid="no-route-membership"
            >
              <h3
                id="no-routes-heading"
                className="text-xs font-black text-stone-200"
              >
                No reading route memberships
              </h3>
              <p className="mt-1 text-[11px] text-amber-200">
                No direct or transitive prerequisites, downstream unlocks, or membership data are returned for this issue.
              </p>
            </section>
          ) : null}
        </>
      ) : null}
    </Modal>
  )
}
