import type { RollRecoveryInfo, RollRecoveryPrerequisite } from '../../../types/rollBootstrap'

interface RollRecoveryCardProps {
  recovery?: RollRecoveryInfo | null
  onReadNow?: (prerequisite: RollRecoveryPrerequisite) => void
  isPending?: boolean
  isLoading?: boolean
  errorMessage?: string | null
}

const diagnosticMessages = {
  cycle_detected: 'This continuity plan contains a cycle, so ComicPile stopped before looping.',
  depth_limit_exceeded: 'This dependency chain is deeper than ComicPile can safely traverse.',
  node_limit_exceeded: 'This dependency graph is larger than ComicPile can safely traverse at once.',
} as const

/** Explain a blocked pending roll without replacing the original selection. */
export function RollRecoveryCard({
  recovery,
  onReadNow,
  isPending = false,
  isLoading = false,
  errorMessage = null,
}: RollRecoveryCardProps) {
  if (isLoading) {
    return (
      <section
        aria-label="Blocked roll recovery"
        aria-busy="true"
        className="mx-auto w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-lg"
      >
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-500">Roll blocked</p>
        <p className="mt-2 text-sm text-stone-300">Checking what needs to be read first…</p>
      </section>
    )
  }

  if (errorMessage) {
    return (
      <section
        aria-label="Blocked roll recovery"
        role="alert"
        className="mx-auto w-full max-w-xl rounded-2xl border border-red-500/30 bg-red-950/20 p-4 shadow-lg"
      >
        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-red-400">Recovery unavailable</p>
        <p className="mt-2 text-sm text-stone-300">{errorMessage}</p>
        <p className="mt-2 text-xs text-stone-400">Your original roll is still preserved.</p>
      </section>
    )
  }

  if (!recovery) return null

  const primaryBlocker = recovery.direct_blockers[0]
  const recommendations = recovery.readable_prerequisites
  const chains = recovery.chains ?? []
  const diagnostics = recovery.diagnostics ?? []

  return (
    <section
      aria-label="Blocked roll recovery"
      className="mx-auto w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-lg"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-500">Roll blocked</p>
      <h2 className="mt-1 text-lg font-black text-stone-100">{recovery.original_thread_title}</h2>
      <p className="mt-2 text-sm text-stone-300">
        Your original roll is still waiting. {primaryBlocker
          ? <><strong>{primaryBlocker.source_label}</strong> has to be read first.</>
          : <>A continuity prerequisite has to be completed first.</>}
      </p>

      {chains.length > 0 && (
        <details className="mt-4 rounded-xl border border-white/10 bg-black/20 px-3 py-2">
          <summary className="cursor-pointer text-xs font-black uppercase tracking-widest text-stone-300">
            Why is this blocked? ({chains.length} {chains.length === 1 ? 'path' : 'paths'})
          </summary>
          <div className="mt-3 space-y-3">
            {chains.map((chain, chainIndex) => (
              <ol
                key={chain.map((node) => `${node.node_type}-${node.node_id}`).join(':')}
                aria-label={`Dependency path ${chainIndex + 1}`}
                className="space-y-1"
              >
                <li className="text-xs font-bold text-stone-400">{recovery.original_thread_title}</li>
                {chain.map((node, index) => (
                  <li
                    key={`${node.node_type}-${node.node_id}-${index}`}
                    className="flex items-center gap-2 pl-2 text-sm text-stone-200"
                  >
                    <span aria-hidden="true" className="text-stone-600">↳</span>
                    <span className="min-w-0 flex-1">
                      {node.label}
                      <span className="ml-2 text-[10px] font-bold uppercase tracking-wider text-stone-500">
                        {node.node_type}
                      </span>
                    </span>
                    {node.is_readable && (
                      <span className="shrink-0 text-[10px] font-black uppercase tracking-wider text-emerald-400">
                        Readable now
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            ))}
          </div>
        </details>
      )}

      {diagnostics.length > 0 && (
        <div role="alert" className="mt-3 rounded-xl border border-red-500/30 bg-red-950/20 px-3 py-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-red-400">Continuity warning</p>
          <ul className="mt-1 space-y-1 text-xs text-stone-300">
            {diagnostics.map((diagnostic) => (
              <li key={`${diagnostic.code}-${diagnostic.node_type}-${diagnostic.node_id}`}>
                {diagnosticMessages[diagnostic.code]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {recommendations.length > 0 ? (
        <div className="mt-4 space-y-2">
          <p className="text-[10px] font-black uppercase tracking-widest text-stone-500">
            {recommendations.length === 1 ? 'Read this first' : 'Readable prerequisites'}
          </p>
          {recommendations.map((prerequisite, index) => {
            const content = (
              <>
                <span className="min-w-0">
                  <span className="block text-sm font-black text-stone-100">{prerequisite.label}</span>
                  {index === 0 && recommendations.length > 1 && (
                    <span className="mt-0.5 block text-[10px] font-bold uppercase tracking-wider text-amber-500">
                      Recommended first
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-xs font-black uppercase tracking-widest text-amber-400">
                  Read now
                </span>
              </>
            )

            return onReadNow ? (
              <button
                key={`${prerequisite.node_type}-${prerequisite.node_id}`}
                type="button"
                onClick={() => onReadNow(prerequisite)}
                disabled={isPending}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-left transition-colors hover:bg-white/10 disabled:opacity-60"
              >
                {content}
              </button>
            ) : (
              <div
                key={`${prerequisite.node_type}-${prerequisite.node_id}`}
                className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-left"
              >
                {content}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="mt-4 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-stone-400">
          No readable prerequisite is available yet. Your original roll will stay preserved while the dependency is blocked.
        </p>
      )}
    </section>
  )
}
