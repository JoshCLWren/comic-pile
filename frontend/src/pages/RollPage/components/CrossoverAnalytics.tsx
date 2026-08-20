import type { ReaderContextCrossover } from '../../../services/api-reader-context'

interface CrossoverAnalyticsProps {
  crossovers: ReaderContextCrossover[]
}

function crossoverHasStats(c: ReaderContextCrossover): boolean {
  return c.applies_to_current_issue && (c.ratings_count > 0 || c.read_count > 0 || c.average_rating !== null)
}

export function CrossoverAnalytics({ crossovers }: CrossoverAnalyticsProps) {
  const applicable = crossovers.filter(crossoverHasStats)

  if (applicable.length === 0) return null

  return (
    <section
      aria-labelledby="crossover-analytics-heading"
      className="rounded-2xl p-3 space-y-2"
      style={{
        border: '1px solid rgba(168,85,247,0.15)',
        backgroundColor: 'var(--theme-bg-panel)',
      }}
    >
      <h4
        id="crossover-analytics-heading"
        className="text-[10px] font-black uppercase tracking-[0.15em] text-stone-500"
      >
        Crossovers
      </h4>
      <div className="space-y-2">
        {applicable.map((c) => (
          <div
            key={c.id}
            className="rounded-xl p-2.5"
            style={{
              border: '1px solid rgba(168,85,247,0.1)',
              backgroundColor: 'rgba(168,85,247,0.04)',
            }}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[11px] font-black text-stone-200 truncate">
                {c.name}
              </span>
              {c.average_rating !== null ? (
                <span
                  className="text-sm font-black tabular-nums shrink-0"
                  style={{ color: 'var(--theme-personal-accent)' }}
                >
                  {c.average_rating.toFixed(2)}
                </span>
              ) : null}
            </div>
            <div className="mt-1 flex gap-3 text-[10px] text-stone-400">
              {c.ratings_count > 0 ? (
                <span>{c.ratings_count} rated</span>
              ) : null}
              {c.read_count > 0 ? (
                <span>{c.read_count} read</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
