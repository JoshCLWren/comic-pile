import type { RollRecoveryInfo, RollRecoveryPrerequisite } from '../../../types/rollBootstrap'

interface RollRecoveryCardProps {
  recovery: RollRecoveryInfo
  onReadNow?: (prerequisite: RollRecoveryPrerequisite) => void
  isPending?: boolean
}

/** Explain a blocked pending roll without replacing the original selection. */
export function RollRecoveryCard({ recovery, onReadNow, isPending = false }: RollRecoveryCardProps) {
  const primaryBlocker = recovery.direct_blockers[0]
  const recommendations = recovery.readable_prerequisites

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
