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
  const evidenceLabel = `From ${discovery.evidence_count} reads across ${discovery.distinct_thread_count} series.`

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
      className="mx-auto w-full max-w-xl rounded-2xl border border-[var(--theme-comic-accent)]/30 bg-[var(--theme-comic-accent)]/20 p-4 shadow-lg"
    >
      <p className="text-[10px] font-black uppercase tracking-[0.2em] text-[var(--theme-comic-accent)]">
        ComicPile noticed something
      </p>
      <p className="mt-2 text-sm text-[var(--theme-text-primary)]">{discovery.prompt}</p>
      <p className="mt-1 text-xs text-[var(--theme-text-muted)]">{evidenceLabel}</p>
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
            className="rounded-lg border border-[var(--theme-comic-accent)]/50 bg-[var(--theme-comic-accent)]/20 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--theme-comic-accent)] transition-colors hover:bg-[var(--theme-comic-accent)]/30 disabled:opacity-50"
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
          className="ml-auto rounded-lg px-2 py-1.5 text-[10px] font-black uppercase tracking-widest text-[var(--theme-text-muted)] transition-colors hover:text-[var(--theme-text-primary)] disabled:opacity-50"
        >
          Not now
        </button>
      </div>
    </section>
  )
}
