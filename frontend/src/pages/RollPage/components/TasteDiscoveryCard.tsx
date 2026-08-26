import { useState } from 'react'
import type { TasteDiscovery, TasteVerdict } from '../../../services/api-taste'

interface TasteDiscoveryCardProps {
  discovery: TasteDiscovery | null
  onRespond: (verdict: TasteVerdict) => Promise<boolean>
  onDismiss: () => Promise<boolean>
}

const VERDICT_ACTIONS = [
  { verdict: 'confirmed', label: 'Yes' },
  { verdict: 'sometimes', label: 'Sometimes' },
  { verdict: 'rejected', label: 'Not really' },
] as const

/**
 * Compact occasional "ComicPile noticed something" card for the Roll page.
 * It renders only while an eligible discovery exists, never blocks rolling
 * or rating, and treats dismissal as a temporary snooze rather than a
 * verdict.
 */
export function TasteDiscoveryCard({ discovery, onRespond, onDismiss }: TasteDiscoveryCardProps) {
  const [pendingAction, setPendingAction] = useState<TasteVerdict | 'dismiss' | null>(null)

  if (!discovery) return null

  const isBusy = pendingAction !== null
  const evidenceLabel = `From ${discovery.evidence_count} reads across ${discovery.distinct_thread_count} ${
    discovery.distinct_thread_count === 1 ? 'thread' : 'threads'
  }.`

  const handleRespond = async (verdict: TasteVerdict) => {
    setPendingAction(verdict)
    try {
      await onRespond(verdict)
    } finally {
      setPendingAction(null)
    }
  }

  const handleDismiss = async () => {
    setPendingAction('dismiss')
    try {
      await onDismiss()
    } finally {
      setPendingAction(null)
    }
  }

  return (
    <section
      aria-label="ComicPile noticed something"
      aria-live="polite"
      data-testid="taste-discovery-card"
      className="mx-auto w-full max-w-xl rounded-2xl border border-amber-500/30 bg-amber-950/20 p-4 shadow-lg"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.2em] text-amber-500">
        ComicPile noticed something
      </p>
      <p className="mt-2 text-sm text-stone-300">{discovery.prompt}</p>
      <p className="mt-1 text-xs text-stone-400">{evidenceLabel}</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {VERDICT_ACTIONS.map(({ verdict, label }) => (
          <button
            key={verdict}
            type="button"
            disabled={isBusy}
            aria-pressed={pendingAction === verdict}
            onClick={() => {
              void handleRespond(verdict)
            }}
            className="rounded-lg border border-amber-600/50 bg-amber-600/20 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-amber-500 transition-colors hover:bg-amber-600/30 disabled:opacity-50"
          >
            {label}
          </button>
        ))}
        <button
          type="button"
          disabled={isBusy}
          onClick={() => {
            void handleDismiss()
          }}
          className="ml-auto rounded-lg px-2 py-1.5 text-[10px] font-black uppercase tracking-widest text-stone-400 transition-colors hover:text-stone-200 disabled:opacity-50"
        >
          Not now
        </button>
      </div>
    </section>
  )
}
