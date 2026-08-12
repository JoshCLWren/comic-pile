import { useContinuityReadiness } from '../../../hooks/useContinuityReadiness'

interface ContinuityReadinessSummaryProps {
  issueId: number | null | undefined
}

export function ContinuityReadinessSummary({ issueId }: ContinuityReadinessSummaryProps) {
  const { readiness, isLoading, error } = useContinuityReadiness(issueId)

  if (issueId == null) {
    return (
      <section
        aria-labelledby="readiness-heading"
        className="rounded-2xl border border-amber-700/30 bg-amber-900/10 p-3"
      >
        <h3 id="readiness-heading" className="text-xs font-black text-amber-300">
          Readiness unavailable
        </h3>
        <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
          ComicPile does not have an exact issue identity for this pending roll yet.
        </p>
      </section>
    )
  }

  if (isLoading) {
    return (
      <section
        aria-labelledby="readiness-heading"
        className="rounded-2xl border border-white/10 bg-white/5 p-3"
        role="status"
        aria-live="polite"
      >
        <h3 id="readiness-heading" className="text-xs font-black text-stone-300">
          Checking reading readiness…
        </h3>
      </section>
    )
  }

  if (error || !readiness) {
    return (
      <section
        aria-labelledby="readiness-heading"
        className="rounded-2xl border border-rose-700/30 bg-rose-950/20 p-3"
        role="alert"
      >
        <h3 id="readiness-heading" className="text-xs font-black text-rose-300">
          Readiness could not be verified
        </h3>
        <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
          The roll stays pending. Retry before treating this issue as safe to read.
        </p>
      </section>
    )
  }

  if (readiness.is_readable) {
    return (
      <section
        aria-labelledby="readiness-heading"
        className="rounded-2xl border border-emerald-700/30 bg-emerald-950/20 p-3"
      >
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="text-emerald-400">✓</span>
          <h3 id="readiness-heading" className="text-xs font-black text-emerald-300">
            Ready to read
          </h3>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-stone-400">
          All known direct continuity prerequisites for this exact issue are satisfied.
        </p>
      </section>
    )
  }

  return (
    <section
      aria-labelledby="readiness-heading"
      className="rounded-2xl border border-rose-700/30 bg-rose-950/20 p-3"
    >
      <h3 id="readiness-heading" className="text-xs font-black text-rose-300">
        Blocked by continuity
      </h3>
      <ul className="mt-2 space-y-1.5" aria-label="Unresolved prerequisites">
        {readiness.blockers.map((blocker) => (
          <li key={blocker.rule_id} className="text-[11px] leading-relaxed text-stone-300">
            <span className="font-bold text-rose-200">{blocker.source_label}</span>
            {blocker.note ? <span className="text-stone-500"> · {blocker.note}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
